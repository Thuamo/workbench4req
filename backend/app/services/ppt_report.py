import io
import json
import re
import unicodedata
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import SessionLocal
from ..models import ModelConfig, Skill, SkillVersion, User
from ..schemas import SkillConfig
from .ai import SYSTEM_POLICY, complete
from .files import store
from .selected_materials import collect_selected


WORKFLOW = 'ppt_report'
COMMAND = '/一页PPT'
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
TEMPLATE = ASSETS / 'one-page-report.pptx'
PPTX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'


def install(db):
    if db.scalar(select(Skill.id).where(Skill.command == COMMAND, Skill.public.is_(True)).limit(1)):
        return
    _, header, prompt = (ASSETS / 'one-page-ppt' / 'SKILL.md').read_text(encoding='utf-8').split('---', 2)
    description = yaml.safe_load(header)['description']
    skill = Skill(name='一页汇报 PPT', command=COMMAND, description=description, public=True)
    db.add(skill)
    db.flush()
    config = SkillConfig(workflow=WORKFLOW, system_prompt=prompt.strip(), allowed_tools=['read_source'], human_confirmation=False)
    version = SkillVersion(skill_id=skill.id, config=config.model_dump())
    db.add(version)
    db.flush()
    skill.current_version_id = version.id


class ReportSection(BaseModel):
    heading: str = Field(min_length=1, max_length=35)
    detail: str = Field(min_length=1, max_length=160)
    citations: list[str] = Field(min_length=1, max_length=50)


class Report(BaseModel):
    headline: str = Field(min_length=1, max_length=100)
    context: str = Field(default='', max_length=140)
    sections: list[ReportSection] = Field(min_length=1, max_length=3)
    speaker_notes: list[str] = Field(default_factory=list, max_length=12)


def display_units(text):
    return sum(1 if unicodedata.east_asian_width(ch) in 'WFA' else 0.72 if ch.isupper() else 0.58 for ch in text)


def one_line(text):
    return ' '.join(text.split())


def checked_report(raw, source_ids):
    report = Report.model_validate_json(raw)
    report.headline = one_line(report.headline)
    report.context = one_line(report.context)
    if not report.headline or display_units(report.headline) > 48 or display_units(report.context) > 50:
        raise ValueError('标题或范围说明超出单页容量')
    for section in report.sections:
        section.heading, section.detail = one_line(section.heading), one_line(section.detail)
        if not section.heading or not section.detail or display_units(section.heading) > 8 or display_units(section.detail) > 65:
            raise ValueError('区块标题或正文超出单页容量')
        section.citations = list(dict.fromkeys(key for key in section.citations if key in source_ids))
        if not section.citations:
            raise ValueError('每个区块须引用选中的需求或文件')
    return report


def render_pptx(report, sources):
    replacements = {'REPORT_HEADLINE': report.headline, 'REPORT_CONTEXT': report.context}
    for i, section in enumerate(report.sections, 1):
        replacements[f'REPORT_LABEL_{i}'] = section.heading
        replacements[f'REPORT_DETAIL_{i}'] = section.detail
    notes = [one_line(note)[:600] for note in report.speaker_notes if note.strip()]
    notes.extend(['汇报区块与来源', *(section.heading + ' — ' + '、'.join(section.citations) for section in report.sections),
                  '所选资料', *(source['key'] + ' ' + source['title'] + ' · ' + source['revision'] +
                              ('（仅取前段）' if source['truncated'] else '') for source in sources)])

    output = io.BytesIO()
    with zipfile.ZipFile(TEMPLATE) as template:
        slide_name = 'ppt/slides/slide1.xml'
        notes_name = 'ppt/notesSlides/notesSlide1.xml'
        slide = ET.fromstring(template.read(slide_name))
        tree = slide.find(f'.//{P}spTree')
        for shape in tree.findall(f'{P}sp'):
            name = shape.find(f'{P}nvSpPr/{P}cNvPr').get('name')
            value = shape.find(f'.//{A}t')
            row = re.fullmatch(r'(divider|label|detail)_(\d+)', name)
            if row and int(row[2]) > len(report.sections):
                tree.remove(shape)
                continue
            if row and len(report.sections) == 2 and row[2] == '2':
                position = shape.find(f'{P}spPr/{A}xfrm/{A}off')
                position.set('y', str(int(position.get('y')) + 45 * 9525))
            if value is not None and value.text in replacements:
                value.text = replacements.pop(value.text)
        if replacements:
            raise RuntimeError('PPT 模板的文本区域不完整')

        notes_root = ET.fromstring(template.read(notes_name))
        notes_added = False
        for body in notes_root.iter(f'{P}txBody'):
            for paragraph in body.findall(f'{A}p'):
                if not any(t.text == 'REPORT_SPEAKER_NOTES' for t in paragraph.iter(f'{A}t')):
                    continue
                index = list(body).index(paragraph)
                body.remove(paragraph)
                for offset, line in enumerate(notes):
                    entry = deepcopy(paragraph)
                    next(entry.iter(f'{A}t')).text = line
                    body.insert(index + offset, entry)
                notes_added = True
        if not notes_added:
            raise RuntimeError('PPT 模板缺少演讲者备注区域')

        updated = {slide_name: slide, notes_name: notes_root}
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as deck:
            for entry in template.namelist():
                data = ET.tostring(updated[entry], encoding='utf-8', xml_declaration=True) if entry in updated else template.read(entry)
                deck.writestr(entry, data)
    return output.getvalue()


def generate(inputs, config, owner, model_id):
    with SessionLocal() as db:
        excerpts = collect_selected(db, db.get(User, owner), inputs.get('report_requirement_ids', []),
                                    inputs.get('report_requirement_revisions', {}), inputs['source_version_ids'])
        source_ids = {source['key'] for source in excerpts}
        system = SYSTEM_POLICY + '\n' + config['system_prompt'] + '''
返回 JSON：headline（标题，最多 42 个中文字）、context（可选的范围说明，最多 45 个中文字）、sections（1 至 3 项）、speaker_notes（口头补充和证据定位，字符串数组）。
每个 section 包含 heading（最多 8 个中文字）、detail（最多 62 个中文字，一至两句）、citations（所选证据编号列表，例如 R1、D1）。
可用的证据编号是本轮 evidence_untrusted 中的 key。标题和正文只用纯文本。按界面指定的受众与目的取舍，缺少事实时写清待确认内容。'''
        request = {'目的与重点': config.get('user_template', '{task}').replace('{task}', inputs['task']),
                   '汇报对象': inputs.get('report_audience', ''), 'evidence_untrusted': excerpts}
        for attempt in range(2):
            raw, _ = complete(db, owner, [{'role': 'system', 'content': system},
                                        {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}],
                              json_output=True, config=db.get(ModelConfig, model_id),
                              temperature=config.get('model_parameters', {}).get('temperature', 0.2), read_timeout=None)
            db.commit()
            try:
                report = checked_report(raw, source_ids)
            except ValueError:
                if attempt:
                    raise RuntimeError('模型未返回符合单页容量和来源要求的提要，请缩小汇报范围后重试') from None
                request['输出修正'] = '重新生成完整 JSON。缩短标题、范围和各区块，确保每区块引用选中的 R 或 D 编号。'
            else:
                break
    sources = [{key:value for key, value in source.items() if key != 'text'} for source in excerpts]
    return {**report.model_dump(), 'sources': sources, 'pptx_hash': store(render_pptx(report, sources))}
