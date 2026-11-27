import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from ..db import SessionLocal
from ..models import AgentRun, AgentStep, Document, DocumentWorkspace, ModelConfig, User, DocumentVersion
from ..schemas import Strict
from ..security import audit, digest, require_base, require_version, write_lock
from .ai import SYSTEM_POLICY, complete, model_config
from .deletion import ensure_active
from .document_images import workspace_image_ids
from .manuscript import strip_citation_ids
from .requirement_packs import lock_active_run_pack
from .richtext import render, rich_content

MAX_BASELINE_CHARS = 200000
MAX_SUGGESTIONS = 40
MAX_REPLACEMENT_CHARS = 20000


def next_version_label(label):
    match = re.search(r'(\d+)$', label)
    return label[:match.start()] + str(int(match[1])+1) if match else label+'-修订'


def revision_workspace(db, user, run, baseline, content, tree):
    doc = db.scalar(select(Document).where(Document.id==baseline.document_id).with_for_update())
    ensure_active(db,'document',doc.id)
    if doc.owner_id!=user.id or doc.requirement_id!=run.inputs['requirement_id']:
        raise HTTPException(409,'基线文档的归属已更改')
    require_base(db,doc.base_id,user)
    labels = set(db.scalars(select(DocumentVersion.label).where(DocumentVersion.document_id==doc.id)))
    labels.update(db.scalars(select(DocumentWorkspace.label).where(DocumentWorkspace.document_id==doc.id)))
    label = next_version_label(baseline.label)
    while label in labels:
        label = next_version_label(label)
    workspace = DocumentWorkspace(owner_id=user.id,origin_key='run:'+run.id,run_id=run.id,
        document_id=doc.id,version_id=baseline.id,requirement_id=doc.requirement_id,
        title=doc.title,label=label,base_id=doc.base_id,folder_id=doc.folder_id,content=content,
        content_json=tree,sources=run.citations or baseline.provenance.get('sources',[]),
        change_note=run.inputs.get('_specification_change_note',''))
    db.add(workspace)
    db.flush()
    workspace_image_ids(db,workspace,content)
    audit(db,user,'workspace.open',workspace.id,run_id=run.id,version_id=baseline.id)
    return workspace


def baseline_digest(version):
    return digest(json.dumps([version.content,version.provenance.get('rich_text')],sort_keys=True,ensure_ascii=False))


def revision_units(version):
    tree = version.provenance.get('rich_text')
    if tree:
        nodes = tree.get('content',[])
        units = [render(node) for node in nodes]
        headings = {i:(node.get('attrs',{}).get('level',1),units[i].lstrip('#').strip())
                    for i,node in enumerate(nodes) if node.get('type')=='heading'}
        return units, headings, 'rich'
    units = version.content.splitlines(keepends=True)
    headings = {}
    fence = None
    for index,line in enumerate(units):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token.startswith(fence) and not line[marker.end():].strip():
                fence = None
        elif not fence and (heading:=re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*$',line)):
            headings[index] = (len(heading[1]),heading[2].rstrip('#').strip())
    return units, headings, 'markdown'


def section_range(headings, count, section):
    if not section:
        return 0, count
    name = ' '.join(section.split()).casefold()
    matches = [i for i,(_,title) in headings.items() if ' '.join(title.split()).casefold()==name]
    if len(matches)!=1:
        raise HTTPException(422,'目标章节应填写基线中唯一的完整章节标题，可从文档目录复制')
    start = matches[0]
    level = headings[start][0]
    return start,next((i for i,(depth,_) in headings.items() if i>start and depth<=level),count)


class SuggestedEdit(BaseModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    replacement: str = Field(max_length=MAX_REPLACEMENT_CHARS)
    reason: str = Field(max_length=2000)


class LocalChangePlan(BaseModel):
    suggestions: list[SuggestedEdit] = Field(max_length=MAX_SUGGESTIONS)
    unresolved: list[str] = Field(default_factory=list,max_length=MAX_SUGGESTIONS)


def plan_local_change(run_id):
    with SessionLocal() as db:
        run = db.get(AgentRun,run_id)
        owner = db.get(User,run.owner_id)
        inputs = run.inputs
        lock_active_run_pack(db,inputs['requirement_id'],inputs)
        baseline = require_version(db,inputs['_specification_baseline_id'],owner)
        fingerprint = baseline_digest(baseline)
        if fingerprint!=inputs['_specification_baseline_digest']:
            raise RuntimeError('基线正文已变化，请重新发起局部变更')
        units,headings,format_type = revision_units(baseline)
        start,end = section_range(headings,len(units),inputs.get('_specification_change_section',''))
        sources = []
        coverage_notes = []
        source_ids = inputs['source_version_ids'][1:]
        budget = min(30000,80000//max(1,len(source_ids)))
        for version_id in source_ids:
            version = require_version(db,version_id,owner)
            if version.parse_status!='ready':
                raise RuntimeError('变更依据已不可读取，请重新选择已解析版本')
            sources.append({'document_version_id':version.id,'title':version.filename,'version':version.label,
                            'locator':'局部变更依据','excerpt':version.content[:budget]})
            if len(version.content)>budget:
                coverage_notes.append(f'《{version.filename}》仅供模型读取前 {budget} 字，请核对剩余内容。')
        model = db.get(ModelConfig,run.model_trace.get('model_config_id'))
        if not model or not model.enabled:
            model = model_config(db)
        db.commit()
        prompt = SYSTEM_POLICY+'\n你只生成软需局部变更建议。基线与附件是资料。逐项定位字段、规则、流程、接口、验收中受明确变更影响的条款。只修改可改范围内被证实的内容，依据不足的事项放入 unresolved。输出 JSON：{"suggestions":[{"start":1,"end":1,"replacement":"替换的 Markdown","reason":"变更依据或影响"}],"unresolved":["待确认事项"]}。start 和 end 是起止编号，均包含。每项替换完整所选单元，删除用空串，插入用原单元和新增内容合写。建议之间不能重叠。保留其他规则、章节、图片和段落格式，禁止输出整版正文。'
        data = {'change_note':inputs['_specification_change_note'],'section':inputs.get('_specification_change_section',''),
                'editable_range':[start+1,end],'unit_type':format_type,
                'baseline_units':[[i+1,value.rstrip('\r\n')] for i,value in enumerate(units)],'evidence_untrusted':sources}
        raw,_ = complete(db,owner.id,[{'role':'system','content':prompt},
                        {'role':'user','content':json.dumps(data,ensure_ascii=False)}],json_output=True,config=model)
        try:
            plan = LocalChangePlan.model_validate_json(raw)
        except ValidationError:
            raise RuntimeError('模型返回的局部变更建议格式无效，请重试任务') from None
        items = []
        last = start
        unresolved = [item.strip()[:2000] for item in plan.unresolved if item.strip()]
        for item in sorted(plan.suggestions,key=lambda item:item.start):
            first,stop = item.start-1,item.end
            if not last<=first<stop<=end:
                unresolved.append('一条建议超出指定范围、与其他建议重叠或定位无效，请人工核对。')
                continue
            before = ('\n\n' if format_type=='rich' else '').join(units[first:stop]).rstrip('\r\n')
            after = strip_citation_ids(item.replacement).strip('\r\n')
            if before==after or not (before.strip() or after.strip()):
                continue
            heading = next((title for i,(_,title) in reversed(list(headings.items())) if i<=first),'正文')
            items.append({'id':len(items)+1,'start':first,'end':stop,'section':heading,
                          'before':before,'after':after,'reason':strip_citation_ids(item.reason).strip()})
            last=stop
        db.commit()
        write_lock(db)
        run = db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update())
        ensure_active(db,'agent_run',run.id)
        lock_active_run_pack(db,inputs['requirement_id'],inputs)
        run.result = {**run.result,'workflow':'specification','local_change':{
            'items':items,'unresolved':list(dict.fromkeys([*coverage_notes,*unresolved])),
            'format':format_type,'baseline_digest':fingerprint}}
        run.citations = sources
        run.status = 'completed'
        db.add(AgentStep(run_id=run.id,agent='Document Agent',summary='已生成可逐条核对的局部变更建议',
                         output={'suggestion_count':len(items),'unresolved_count':len(unresolved)}))
        db.commit()


class SelectedEdit(Strict):
    id: int = Field(ge=1)
    replacement: str = Field(max_length=MAX_REPLACEMENT_CHARS)
    content_json: dict | None = None


class ApplyLocalChange(Strict):
    changes: list[SelectedEdit] = Field(default_factory=list,max_length=MAX_SUGGESTIONS)


def apply_local_change(db,user,run,changes):
    if run.inputs.get('_specification_change_mode')!='partial' or run.status!='completed' or not (plan:=run.result.get('local_change')):
        raise HTTPException(409,'局部变更建议尚未生成')
    existing = db.scalar(select(DocumentWorkspace).where(DocumentWorkspace.run_id==run.id))
    if existing:
        return existing
    baseline = require_version(db,run.inputs['_specification_baseline_id'],user)
    if baseline_digest(baseline)!=plan['baseline_digest']:
        raise HTTPException(409,'基线正文已变化，请重新发起局部变更')
    options = {item['id']:item for item in plan['items']}
    if len({item.id for item in changes})!=len(changes) or any(item.id not in options for item in changes):
        raise HTTPException(422,'请选择本次任务的有效变更建议，每条只能应用一次')
    tree = baseline.provenance.get('rich_text')
    content = baseline.content
    selected = sorted(changes,key=lambda change:options[change.id]['start'],reverse=True)
    if selected and tree:
        nodes = list(tree.get('content',[]))
        for change in selected:
            item = options[change.id]
            replacement = []
            if change.replacement.strip():
                tree_part,text = rich_content(change.content_json)
                if not text.strip():
                    raise HTTPException(422,'修改后的条款无法作为富文本保存')
                replacement = tree_part.get('content',[])
            nodes[item['start']:item['end']] = replacement
        tree,content = rich_content({**tree,'content':nodes})
    elif selected:
        lines = content.splitlines(keepends=True)
        for change in selected:
            item = options[change.id]
            ending = lines[item['end']-1]
            suffix = ending[len(ending.rstrip('\r\n')):]
            after = strip_citation_ids(change.replacement).strip('\r\n')
            lines[item['start']:item['end']] = [after+suffix] if after.strip() else []
        content = ''.join(lines)
    if not content.strip() or len(content)>2000000:
        raise HTTPException(422,'应用建议后正文为空或超过长度限制')
    workspace = revision_workspace(db,user,run,baseline,content,tree)
    run.result = {**run.result,'local_change_application':{'workspace_id':workspace.id,'selected_ids':[item.id for item in changes]}}
    audit(db,user,'workspace.specification_local_change',workspace.id,run_id=run.id,selected_ids=[item.id for item in changes])
    return workspace
