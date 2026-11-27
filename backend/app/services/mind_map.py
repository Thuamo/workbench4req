import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db import SessionLocal
from ..models import ModelConfig, Skill, SkillVersion, User
from ..schemas import SkillConfig
from .ai import SYSTEM_POLICY, complete
from .selected_materials import collect_selected
from .uml import render


WORKFLOW = 'mind_map'
COMMAND = '/思维导图'
SKILL_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'mind-map' / 'SKILL.md'
# Keep free text out of PlantUML markup and control sequences.
DIAGRAM_LITERAL = str.maketrans('!*_~/\\[]<>{}#%$@`|=:+&', '！＊＿～／＼［］＜＞｛｝＃％＄＠｀｜＝：＋＆')
NODE_STATUS = {'confirmed': '', 'conflict': '【冲突】', 'pending': '【待确认】'}


class Node(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    label: str = Field(min_length=1, max_length=36)
    detail: str = Field(default='', max_length=240)
    status: Literal['confirmed', 'conflict', 'pending'] = 'confirmed'
    citations: list[str] = Field(default_factory=list)
    children: list['Node'] = Field(default_factory=list, max_length=12)


class MindMap(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    title: str = Field(min_length=1, max_length=36)
    branches: list[Node] = Field(min_length=1, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=10)


def install(db):
    if db.scalar(select(Skill.id).where(Skill.command == COMMAND, Skill.public.is_(True)).limit(1)):
        return
    _, header, prompt = SKILL_PATH.read_text(encoding='utf-8').split('---', 2)
    skill = Skill(name='思维导图生成', command=COMMAND, description=yaml.safe_load(header)['description'], public=True)
    db.add(skill)
    db.flush()
    config = SkillConfig(workflow=WORKFLOW, system_prompt=prompt.strip(), allowed_tools=['read_source'], human_confirmation=False)
    version = SkillVersion(skill_id=skill.id, config=config.model_dump())
    db.add(version)
    db.flush()
    skill.current_version_id = version.id


def checked_map(raw, source_ids):
    mind_map = MindMap.model_validate_json(raw)
    stack = [(node, 1) for node in mind_map.branches]
    count = 1
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 4 or count > 40:
            raise ValueError('导图超过层级或节点数限制')
        if any(key not in source_ids for key in node.citations):
            raise ValueError('来源编号不在所选资料中')
        node.citations = list(dict.fromkeys(node.citations))
        if (not node.children or node.detail or node.status != 'confirmed') and not node.citations:
            raise ValueError('内容节点需要标注来源')
        stack.extend((child, depth + 1) for child in node.children)
    return mind_map, count


def plantuml_source(mind_map):
    def literal(text):
        return ' '.join(text.translate(DIAGRAM_LITERAL).split())

    def branch_lines(nodes, depth):
        for node in nodes:
            suffix = ' (' + '、'.join(node.citations[:3]) + ')' if node.citations else ''
            yield f"{'*' * depth} {NODE_STATUS[node.status]}{literal(node.label)}{suffix}"
            yield from branch_lines(node.children, depth + 1)

    split = (len(mind_map.branches) + 1) // 2
    lines = ['@startmindmap', '* ' + literal(mind_map.title), *branch_lines(mind_map.branches[:split], 2)]
    if split < len(mind_map.branches):
        lines.extend(['left side', *branch_lines(mind_map.branches[split:], 2)])
    return '\n'.join([*lines, '@endmindmap', ''])


def generate(inputs, config, owner, model_id):
    with SessionLocal() as db:
        excerpts = collect_selected(db, db.get(User, owner), inputs.get('mind_map_requirement_ids', []),
                                    inputs.get('mind_map_requirement_revisions', {}), inputs['source_version_ids'])
        source_ids = {source['key'] for source in excerpts}
        system = SYSTEM_POLICY + '\n' + config['system_prompt'] + '''
返回一个 JSON 对象，包含 title（中心主题）、branches（节点数组）和 notes（备注字符串数组）。
每个节点有 label（简短名称）、detail（可选补充说明与原文定位）、status（confirmed、conflict 或 pending）、
citations（证据编号数组）和 children（递归的节点数组）。confirmed 表示常规内容，conflict 表示冲突，pending 表示待确认。
中心与节点名称最多 36 字符，说明最多 240 字符，最多 8 个一级分支。中心主题以下最多 4 层，含中心节点总计最多 40 个节点。
每个叶节点、带说明的节点以及冲突和待确认节点都须引用本轮选中资料的 key。备注最多 10 项，按需要说明覆盖范围和定位。使用纯文本。'''
        request = {'梳理范围与重点': config.get('user_template', '{task}').replace('{task}', inputs['task']),
                   'evidence_untrusted': excerpts}
        for attempt in range(2):
            raw, _ = complete(db, owner, [{'role': 'system', 'content': system},
                                        {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}],
                              json_output=True, config=db.get(ModelConfig, model_id),
                              temperature=config.get('model_parameters', {}).get('temperature', 0.2), read_timeout=None)
            db.commit()
            try:
                mind_map, count = checked_map(raw, source_ids)
            except ValueError:
                if attempt:
                    raise RuntimeError('模型未返回符合层级和来源要求的导图，请调整梳理范围后重试') from None
                request['输出修正'] = '重新返回完整 JSON。控制层级和节点数，为所有内容节点补齐真实的材料编号。'
            else:
                break
    svg_hash, render_status = render(plantuml_source(mind_map), 'mind_map')
    sources = [{key: value for key, value in source.items() if key != 'text'} for source in excerpts]
    return {**mind_map.model_dump(), 'node_count': count, 'sources': sources, 'svg_hash': svg_hash,
            'render_status': render_status}
