from fastapi import HTTPException
from jsonschema import ValidationError, validate
from pydantic import Field
from sqlalchemy import and_, or_, select
from typing import Literal
from uuid import UUID

from ..models import AgentRun, Document, DocumentVersion, Outbox, ProcessingTaskContext, Requirement, Skill, SkillVersion
from ..schemas import RunInput, Strict
from ..security import audit, can_version, owned, require_base, write_lock
from .ai import model_config
from .deletion import active_filter, ensure_active, requirement_filter
from .journey import context_for
from .ledger_fill import workflow
from .processing_tasks import create_agent_run, queue_agent_run
from .requirement_packs import Stage, pack_for, pack_sources, specification_versions, run_pack_id, workflow_stage, linked_versions
from .uml import DIAGRAM_TYPES
from .specification_revision import MAX_BASELINE_CHARS, baseline_digest, revision_units, revision_workspace, section_range


INITIALIZATION_TASKS = {
    'clarification': ('需求缺口识别', '/澄清计划'),
    'impact': ('变更影响分析', '/关联分析'),
    'specification': ('生成软需草稿', '/软需生成'),
    'ledger_fill': ('澄清台账自动填报', '/澄清台账填报'),
}


class InitializeInput(Strict):
    source_version_id: str | None = None
    target_system: str = Field(default='', max_length=200)
    skill_id: str | None = None
    fixed_template: bool = True


class LaunchOptions(InitializeInput):
    basic_tasks: list[Literal['clarification', 'impact', 'specification', 'ledger_fill']] = Field(default_factory=list, max_length=4)
    skill_ids: list[str] = Field(default_factory=list, max_length=50)
    diagram_types: list[str] = Field(default_factory=list, max_length=len(DIAGRAM_TYPES))
    quality_version_id: str | None = None
    source_version_ids: list[str] | None = Field(default=None,max_length=10)


class LaunchInput(LaunchOptions):
    request_id: UUID | None = None
    pack_id: str | None = None
    stage: Stage | None = None


class StageLaunchInput(LaunchOptions):
    stage: Stage


class ChangeInput(Strict):
    mode: Literal['manual','partial','full'] | None = None
    baseline_version_id: str | None = None
    source_version_id: str | None = None
    primary_change_version_id: str | None = None
    section: str = Field(default='',max_length=300)
    change_note: str = Field(default='',max_length=10000)
    target_system: str = Field(default='',max_length=200)
    request_id: UUID | None = None
    source_version_ids: list[str] | None = Field(default=None,max_length=10)


class PackLaunchInput(Strict):
    request_id: UUID
    stages: list[StageLaunchInput] = Field(default_factory=list, max_length=3)
    change: ChangeInput | None = None


CHANGE_COMMAND = '/软需变更'


def is_change_skill(skill):
    return skill.public and skill.command == CHANGE_COMMAND


def change_available(db, user):
    return next(((skill, version) for skill, version in available_skills(db,user) if is_change_skill(skill)), None)


def input_versions(db, requirement, user):
    selected = db.get(DocumentVersion, requirement.source_version_id) if requirement.source_version_id else None
    direct = Document.requirement_id == requirement.id
    scope = or_(direct, Document.id == selected.document_id) if selected else direct
    documents = db.scalars(select(Document).where(scope, active_filter('document', Document.id),
                                                   Document.kind.in_(['business', 'reference']))).all()
    sources, references = [], []
    for document in documents:
        versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)
                              .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id)).all()
        visible = [version for version in versions if can_version(db, version, user)]
        primary = selected and document.id == selected.document_id
        if not visible:
            continue
        if primary or document.kind == 'business':
            latest = visible[0]
            sources.append((document, latest))
            if primary and selected.id != latest.id and can_version(db, selected, user):
                sources.append((document, selected))
        elif ready := next((version for version in visible if version.parse_status == 'ready'), None):
            references.append(ready.id)
    sources.sort(key=lambda item: (item[1].created_at, item[1].id), reverse=True)
    return sources, sorted(references)


def suggested_source(requirement, sources):
    if not sources:
        return None
    primary = next((doc.id for doc, version in sources if version.id == requirement.source_version_id), None)
    document_ids = {doc.id for doc, _ in sources}
    if primary or len(document_ids) == 1:
        return next(version.id for doc, version in sources if doc.id == (primary or sources[0][0].id))
    return None


def consolidation_sources(db, requirement, pack_id, user, sources):
    items = {v.id:(doc,v) for doc,v in sources}
    for doc, version in specification_versions(db,requirement,pack_id,user):
        items[version.id] = (doc,version)
    for link, doc, version in linked_versions(db,[pack_id],user):
        if link.stage=='consolidation':
            items[version.id] = (doc,version)
    return list(items.values())


def selected_pack_sources(options, sources):
    if options.source_version_id and options.source_version_ids is not None:
        raise HTTPException(422,'请使用统一的关联文档选择方式')
    ids = options.source_version_ids if options.source_version_ids is not None else (
        [options.source_version_id] if options.source_version_id else [])
    ready = {version.id for _,version in sources if version.parse_status=='ready'}
    if len(ids)!=len(set(ids)) or any(vid not in ready for vid in ids):
        raise HTTPException(422,'请选择当前需求包内已解析的关联文档版本，不能重复选择')
    return ids


def target_system(requirement):
    tags = set(value.strip() for value in requirement.tags.get('系统', []) if value.strip())
    return next(iter(tags)) if len(tags) == 1 else ''


def quality_versions(db, requirement, user):
    rows = db.execute(select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
                      .where(Document.requirement_id == requirement.id, Document.kind == 'specification',
                             active_filter('document', Document.id), DocumentVersion.parse_status == 'ready')
                      .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())).all()
    return [(doc, version) for doc, version in rows if can_version(db, version, user)]


def available_skills(db, user):
    rows = db.execute(select(Skill, SkillVersion).join(SkillVersion, Skill.current_version_id == SkillVersion.id)
                      .where(Skill.enabled.is_(True), or_(Skill.public.is_(True), Skill.owner_id == user.id),
                             active_filter('skill', Skill.id)).order_by(Skill.name, Skill.id)).all()
    return rows


def basic_skill_options(rows, kind):
    _, command = INITIALIZATION_TASKS[kind]
    matches = [(s, v) for s, v in rows if not is_change_skill(s) and workflow(v.config) == kind and 'read_source' in v.config.get('allowed_tools', [])]
    if kind == 'ledger_fill':
        return sorted(matches, key=lambda row: (not bool(row[1].config.get('package_metadata', {}).get('file_hash')),
                                               row[0].command != command or not row[0].public))
    return sorted(matches, key=lambda row: (row[0].command != command or not row[0].public, not row[0].public))


def extra_skills(rows):
    defaults = {kind: matches[0][0] for kind in INITIALIZATION_TASKS if (matches := basic_skill_options(rows, kind))}
    result = []
    for skill, version in rows:
        kind = workflow(version.config)
        basic = defaults.get(kind)
        if is_change_skill(skill) or kind == 'qa' or (basic and (skill.id == basic.id or skill.public and
                (skill.command == INITIALIZATION_TASKS[kind][1] or skill.name == basic.name))):
            continue
        result.append((skill, version))
    return result


def initialize(db, user, requirement_id, options, *, commit=True):
    return launch(db, user, requirement_id,
                  LaunchInput(**options.model_dump(), basic_tasks=list(INITIALIZATION_TASKS)), commit=commit)


def launch_pack_tasks(db, user, requirement_id, pack_id, data: PackLaunchInput):
    if not data.stages and not data.change:
        raise HTTPException(422, '请至少选择一项任务')
    if len({options.stage for options in data.stages}) != len(data.stages):
        raise HTTPException(422, '同一阶段只能提交一组任务')
    if any(workflow_stage(kind) != options.stage for options in data.stages for kind in options.basic_tasks):
        raise HTTPException(422, '所选基础任务不属于当前阶段')
    skill_ids = [skill_id for options in data.stages for skill_id in options.skill_ids]
    if len(set(skill_ids)) != len(skill_ids):
        raise HTTPException(422, '同一技能只能在本次发起中选择一次')

    write_lock(db)
    task_ids = {}
    for stage_options in data.stages:
        options = LaunchInput(**stage_options.model_dump(), pack_id=pack_id, request_id=data.request_id)
        result = launch(db, user, requirement_id, options, commit=False)
        task_ids.update(result['task_ids'])
    if data.change:
        options = data.change.model_copy(update={'request_id': data.request_id})
        result = launch_change(db, user, requirement_id, pack_id, options, commit=False)
        task_ids['specification_change'] = result['id']
    db.commit()
    return {'task_ids': task_ids}


def launch(db, user, requirement_id, options: LaunchInput, *, commit=True):
    if commit:
        write_lock(db)
    requirement = owned(db.scalar(select(Requirement).where(Requirement.id == requirement_id).with_for_update()), user)
    ensure_active(db, 'requirement', requirement.id)
    context = context_for(db, requirement)
    if (context and context.kind != 'business') or not db.scalar(select(Requirement.id).where(Requirement.id == requirement.id, requirement_filter())):
        raise HTTPException(422, '请从业务需求详情发起任务')
    if bool(options.pack_id) != bool(options.stage):
        raise HTTPException(422, '请选择需求包和阶段')
    if options.source_version_ids is not None and not options.pack_id:
        raise HTTPException(422,'请从需求包选择关联文档')
    pack = pack_for(db, requirement.id, options.pack_id, persist=True) if options.pack_id else None
    basic_tasks = set(options.basic_tasks)
    skill_ids = set(options.skill_ids)
    if not basic_tasks and not skill_ids:
        raise HTTPException(422, '请至少选择一项任务')
    if len(skill_ids)!=len(options.skill_ids) or len(basic_tasks)!=len(options.basic_tasks):
        raise HTTPException(422, '任务选择不能重复')

    existing = {}
    runs = db.execute(select(AgentRun, SkillVersion).join(SkillVersion, AgentRun.skill_version_id == SkillVersion.id)
                      .outerjoin(ProcessingTaskContext, ProcessingTaskContext.run_id == AgentRun.id)
                      .where(AgentRun.owner_id == user.id, active_filter('agent_run', AgentRun.id),
                             or_(ProcessingTaskContext.requirement_id == requirement.id,
                                 and_(ProcessingTaskContext.run_id.is_(None),
                                      AgentRun.inputs['requirement_id'].as_string() == requirement.id)))
                      .order_by(AgentRun.created_at.desc(), AgentRun.id)).all()
    request_id = str(options.request_id) if options.request_id else None
    for run, version in runs:
        if run_pack_id(requirement.id, run.inputs) != (pack.id if pack else requirement.id):
            continue
        kind = workflow(version.config)
        if run.inputs.get('_requirement_skill_task'):
            key = f'skill:{version.skill_id}'
            if request_id and run.inputs.get('_requirement_launch_id')==request_id and version.skill_id in skill_ids:
                existing.setdefault(key, run.id)
        elif kind in basic_tasks:
            existing.setdefault(kind, run.id)
    missing = [kind for kind in INITIALIZATION_TASKS if kind in basic_tasks and kind not in existing]
    requested_skills = [skill_id for skill_id in options.skill_ids if f'skill:{skill_id}' not in existing]
    if not missing and not requested_skills:
        return {'task_ids': existing, 'created_count': 0}

    system = options.target_system.strip() or target_system(requirement)
    skills = available_skills(db, user)
    configurations = []
    for kind in missing:
        label, _ = INITIALIZATION_TASKS[kind]
        matches = basic_skill_options(skills, kind)
        if kind == 'specification' and options.skill_id:
            matches = [(s, v) for s, v in matches if s.id == options.skill_id]
        if not matches:
            raise HTTPException(409, f'请先启用支持读取业务资料的「{label}」技能')
        configurations.append((kind, label, matches[0][1]))

    skill_options = {s.id: (s, v) for s, v in extra_skills(skills)}
    for skill_id in requested_skills:
        if skill_id not in skill_options:
            raise HTTPException(422, '所选技能任务不可用，请刷新后重新选择')
        skill, version = skill_options[skill_id]
        if any(v.skill_id==skill_id for _, _, v in configurations):
            raise HTTPException(422, f'「{skill.name}」已用于所选基础任务，请取消重复选择')
        configurations.append((f'skill:{skill_id}', skill.name, version))

    kinds = {workflow(version.config) for _, _, version in configurations}
    if pack and any(workflow_stage(kind) != options.stage for kind in kinds | basic_tasks):
        raise HTTPException(422, '所选任务不属于当前阶段')
    if pack:
        sources = pack_sources(db,requirement,pack.id,user)
        if options.stage=='consolidation':
            sources = consolidation_sources(db,requirement,pack.id,user,sources)
        source_ids=selected_pack_sources(options,sources)
    else:
        sources, references = input_versions(db, requirement, user)
        source_id=options.source_version_id
        if not source_id and kinds - {'ppt_report','mind_map','quality'}:
            source_id=suggested_source(requirement,sources)
        source=next((version for _,version in sources if version.id==source_id and version.parse_status=='ready'),None)
        if options.source_version_id and not source:
            raise HTTPException(422,'请选择已解析的业务需求说明书版本')
        source_ids=[source.id,*references] if source else []
    needs_source = bool(kinds - {'ppt_report','mind_map','quality'}) or bool(pack and options.stage=='consolidation')
    if needs_source and not source_ids:
        raise HTTPException(422,'请至少选择一个已解析的关联文档版本' if pack else '请选择已解析的业务需求说明书版本')
    quality_target = None
    if 'quality' in kinds:
        eligible = specification_versions(db,requirement,pack.id,user) if pack else quality_versions(db,requirement,user)
        quality_target = next((version for _, version in eligible
                               if version.id == options.quality_version_id), None)
        if not quality_target:
            raise HTTPException(422, '请选择本需求下已解析的软需版本进行质量核查')
    if 'specification' in kinds and not system:
        raise HTTPException(422, '请填写目标系统')
    if 'uml' in kinds and (not options.diagram_types or len(set(options.diagram_types))!=len(options.diagram_types)
                            or any(kind not in DIAGRAM_TYPES for kind in options.diagram_types)):
        raise HTTPException(422, '请为 UML 技能选择至少一种有效图种，每种图只能选择一次')

    prepared = []
    for key, label, version in configurations:
        kind = workflow(version.config)
        is_extra = key.startswith('skill:')
        if kind == 'specification' and not options.fixed_template and not version.config.get('human_confirmation', True):
            raise HTTPException(422, '所选技能未启用人工提纲确认，请选择标准目录或更换技能')
        task = '\n'.join(part for part in (f'{label}｜{requirement.number} {requirement.title}', requirement.description,
                         '验收标准：' + requirement.acceptance if requirement.acceptance else '') if part)
        diagram_types = options.diagram_types if kind=='uml' else []
        inputs = RunInput(task=task[:20000], requirement_id=requirement.id, source_version_ids=source_ids,
                          target_system=system, fixed_template=kind == 'specification' and options.fixed_template,
                          diagram_types=diagram_types, report_requirement_ids=[requirement.id] if kind=='ppt_report' and not pack else [],
                          mind_map_requirement_ids=[requirement.id] if kind=='mind_map' and not pack else [])
        excluded = {'diagram_types','report_requirement_ids','report_audience'} if is_extra else set()
        payload=inputs.model_dump(exclude={key for key in excluded | {'mind_map_requirement_ids'} if not getattr(inputs,key)})
        if kind=='quality':
            payload['source_version_ids']=list(dict.fromkeys([quality_target.id,*source_ids]))
        try:
            validate(payload, version.config['input_schema'])
        except ValidationError as error:
            raise HTTPException(422, f'「{label}」设置不符合技能要求：{error.message}') from error
        for base_id in ([] if kind in ('uml','ppt_report','mind_map') else version.config.get('base_ids', [])):
            require_base(db, base_id, user)
        if kind=='ppt_report':
            payload['report_requirement_revisions']={} if pack else {requirement.id: requirement.revision}
        if kind=='mind_map':
            payload['mind_map_requirement_revisions']={} if pack else {requirement.id: requirement.revision}
        if kind=='quality':
            payload['_quality_version_id']=quality_target.id
        payload.update({'_requirement_skill_task': True, '_requirement_launch_id': request_id} if is_extra else {'_initialization_task': key})
        if pack:
            payload.update({'_requirement_pack_id':pack.id,'_requirement_stage':options.stage})
        strategy={'uml': 'selected-versions', 'ppt_report': 'selected-requirements-and-versions', 'mind_map': 'selected-requirements-and-versions'}.get(kind, 'zh-bm25+rrf-vector-v1')
        prepared.append((key, version, payload, strategy))

    model = model_config(db)
    created = {}
    for key, version, inputs, strategy in prepared:
        run = queue_agent_run(db, user, version, inputs, {'model_config_id': model.id, 'model': model.model, 'retrieval_strategy': strategy})
        created[key] = run.id
    audit(db, user, 'requirement.launch_tasks' if request_id or skill_ids else 'requirement.initialize_tasks',
          requirement.id, task_ids=created, source_version_id=source_ids[0] if source_ids else None, source_version_ids=source_ids,
          pack_id=pack.id if pack else None)
    if commit:
        db.commit()
    return {'task_ids': {**existing, **created}, 'created_count': len(created)}


def initialization_view(db, user, requirement, runs, pack_id=None):
    context = context_for(db, requirement)
    if context and context.kind != 'business':
        return None
    sources = pack_sources(db,requirement,pack_id,user) if pack_id else input_versions(db, requirement, user)[0]
    present = {run['workflow'] for run in runs if not run.get('requirement_skill_task')}
    missing = [kind for kind in INITIALIZATION_TASKS if kind not in present]
    skills = available_skills(db, user)

    def source_record(document, version):
        error = None
        if version.parse_status == 'failed':
            error = db.scalar(select(Outbox.error).where(Outbox.kind == 'parse', Outbox.resource_id == version.id))
        return {'id': version.id, 'title': document.title, 'filename':version.filename, 'label': version.label, 'parse_status': version.parse_status,
                'error': error, 'can_retry': version.creator_id == user.id and version.status == 'draft'}

    specs = specification_versions(db,requirement,pack_id,user) if pack_id else quality_versions(db,requirement,user)
    return {'sources': [source_record(doc, version) for doc, version in sources],
            'consolidation_sources': [source_record(doc, version) for doc, version in
                consolidation_sources(db,requirement,pack_id,user,sources)] if pack_id else [],
            'quality_versions': [source_record(doc, version) for doc, version in specs],
            'baseline_versions': [source_record(doc, version) for doc, version in specs if doc.owner_id==user.id],
            'suggested_source_id': suggested_source(requirement, sources), 'target_system': target_system(requirement),
            'skills': [{'id': s.id, 'name': s.name, 'human_confirmation': v.config.get('human_confirmation', True)}
                       for s, v in basic_skill_options(skills, 'specification')] if 'specification' in missing else [],
            'extra_skills': [{'id': s.id, 'name': s.name, 'description': s.description, 'workflow': workflow(v.config),
                              'human_confirmation': v.config.get('human_confirmation', True)} for s, v in extra_skills(skills)],
            'missing': missing}


def launch_change(db, user, requirement_id, pack_id, options, *, commit=True):
    from .requirement_packs import lock_requirement
    if commit:
        write_lock(db)
    requirement = lock_requirement(db,user,requirement_id)
    pack = pack_for(db,requirement.id,pack_id,persist=True)
    request_id = str(options.request_id) if options.request_id else None
    if request_id:
        existing = db.scalar(select(AgentRun.id).where(AgentRun.owner_id==user.id,
            AgentRun.inputs['_requirement_pack_id'].as_string()==pack.id,
            AgentRun.inputs['_specification_change_request'].as_string()==request_id,
            active_filter('agent_run',AgentRun.id)))
        if existing:
            return {'id':existing}
    skill = change_available(db,user)
    if not skill:
        raise HTTPException(409,'请先启用「软需变更」技能')
    _, skill_version = skill
    baselines = [(doc,version) for doc,version in specification_versions(db,requirement,pack.id,user)
                 if doc.owner_id==user.id]
    baseline = next((version for _,version in baselines
                     if not options.baseline_version_id or version.id==options.baseline_version_id),None)
    if not baseline:
        raise HTTPException(422,'请先为该需求包确认一个软需版本，或选择本包可用的基线')
    mode = options.mode or 'full'
    new_sources = selected_pack_sources(options,pack_sources(db,requirement,pack.id,user)) if mode!='manual' else []
    note = options.change_note.strip()
    section = options.section.strip()
    primary = options.primary_change_version_id
    if mode=='partial':
        if not note:
            raise HTTPException(422,'请填写局部变更说明')
        if len(baseline.content)>MAX_BASELINE_CHARS:
            raise HTTPException(422,'局部变更支持最多20万字的基线软需，请使用较短版本或手动改版')
        units, headings, _ = revision_units(baseline)
        if not any(unit.strip() for unit in units):
            raise HTTPException(422,'基线软需没有可编辑的正文')
        section_range(headings,len(units),section)
    elif options.mode=='full' and (not primary or primary not in new_sources or primary==baseline.id):
        raise HTTPException(422,'请从所选文件中指定完整的新版需求说明书')
    elif options.mode is None and not new_sources and not note:
        raise HTTPException(422,'请选择新的需求文档或填写变更说明')
    system = options.target_system.strip() or target_system(requirement)
    title = {'manual':'软需手动改版','partial':'软需局部变更','full':'软需整版重编'}[mode] if options.mode else '软需变更'
    task = f'{title}｜{requirement.number} {requirement.title}'
    if mode=='full':
        task += '\n按核定基线生成完整新版软需。'
    if note:
        task += '\n本次变更说明：' + note
    source_ids = list(dict.fromkeys([baseline.id,*([primary] if primary in new_sources else []),*new_sources]))
    payload = RunInput(task=task[:20000],requirement_id=requirement.id,source_version_ids=source_ids,
                       target_system=system,fixed_template=True,reuse_analysis=False).model_dump()
    payload.update(_requirement_skill_task=True, _requirement_pack_id=pack.id, _requirement_stage='specification',
                   _specification_baseline_id=baseline.id, _specification_change_request=request_id,
                   _specification_change_note=note,_specification_change_mode=mode)
    if mode=='partial':
        payload.update(_specification_change_section=section,_specification_baseline_digest=baseline_digest(baseline))
    if mode=='full' and primary:
        payload['_specification_primary_change_id']=primary
    if mode=='manual':
        run = create_agent_run(db,user,skill_version,payload,{},status='completed')
        revision_workspace(db,user,run,baseline,baseline.content,baseline.provenance.get('rich_text'))
    else:
        model = model_config(db)
        run = queue_agent_run(db,user,skill_version,payload,
                              {'model_config_id':model.id,'model':model.model,'retrieval_strategy':'selected-versions'})
    audit(db,user,'requirement.pack_change_launch',run.id,pack_id=pack.id,baseline_version_id=baseline.id,mode=mode)
    if commit:
        db.commit()
    return {'id':run.id}
