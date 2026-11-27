import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from jsonschema import validate as validate_schema, ValidationError, SchemaError
from ..db import get_db
from ..models import User, Skill, SkillVersion, AgentRun, AgentStep, Outbox, Conversation, DocumentVersion, Document, Question, Requirement, Relation, Folder, ModelConfig
from ..schemas import SkillInput, RunInput
from ..security import current_user, owned, require_version, require_base, audit, write_lock
from ..serialize import record
from ..services.ai import model_config, complete, SYSTEM_POLICY
from ..services.files import store,text_blocks,blob
from ..config import settings
from ..services.skill_packages import read_skill_package, export_skill_package
from ..security import digest
from ..services.outlines import normalize_outline
from ..services.ledger_fill import workflow as effective_workflow
from ..services.manuscript import assemble_sections
from ..services.processing_tasks import task_context,linked_id,linked_requirement,link_document,task_record,associate_task,queue_agent_run
from ..services.requirement_initialization import (InitializeInput, LaunchInput, PackLaunchInput, ChangeInput,
                                                  initialize, launch, launch_pack_tasks, launch_change, is_change_skill)
from ..services.requirement_packs import assign_specification, lock_active_run_pack
from ..services.journey import context_for, requirement_record

from ..services.deletion import active_filter, ensure_active, is_deleted,requirement_filter
from ..services.uml import APPROXIMATE, DIAGRAM_TYPES
from ..services.ppt_report import PPTX_MEDIA_TYPE
from ..services.selected_materials import selected_requirements
from ..services.ppt_report_preview import report_preview

router=APIRouter(tags=['技能与 Agent'])


def skill_allowed(skill: Skill,user: User,db: Session):
    if not skill or (not skill.public and skill.owner_id!=user.id):
        raise HTTPException(404,'技能不存在或未授权')
    ensure_active(db,'skill',skill.id)
    return skill


@router.get('/skills')
def skills(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return [{**record(s),'config':{**db.get(SkillVersion,s.current_version_id).config,'workflow':effective_workflow(db.get(SkillVersion,s.current_version_id).config)}} for s in db.scalars(select(Skill).where(active_filter('skill',Skill.id))).all() if s.public or s.owner_id==user.id]


@router.get('/uml/diagram-types')
def uml_diagram_types(user: User=Depends(current_user)):
    return [{'id': key, 'label': label, 'approximate': key in APPROXIMATE}
            for key, (label, _) in DIAGRAM_TYPES.items()]


def schema_check(config):
    from ..services.delivery import validate_contract
    validate_contract(config.delivery_template)
    from jsonschema.validators import validator_for
    try:
        for schema in [config.input_schema,config.output_schema]:
            validator_for(schema).check_schema(schema)
    except SchemaError:
        raise HTTPException(422,'技能 Schema 无效')
    temperature=config.model_parameters.get('temperature',0.2)
    if not isinstance(temperature,(int,float)) or not 0<=temperature<=2:
        raise HTTPException(422,'temperature 应在 0 到 2 之间')


@router.post('/skills')
def create_skill(data: SkillInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return new_skill(data,user,db)


def new_skill(data: SkillInput,user: User,db: Session,package_metadata: dict | None=None):
    data=data.model_copy(deep=True)
    data.config.package_metadata=package_metadata or {}
    if data.public and user.role!='super_admin':
        raise HTTPException(403,'公共技能由管理员治理')
    schema_check(data.config)
    for bid in data.config.base_ids:
        require_base(db,bid,user)
    skill=Skill(owner_id=user.id,name=data.name,command=data.command,description=data.description,public=data.public)
    db.add(skill)
    db.flush()
    version=SkillVersion(skill_id=skill.id,creator_id=user.id,config=data.config.model_dump())
    db.add(version)
    db.flush()
    skill.current_version_id=version.id
    audit(db,user,'skill.create',skill.id)
    db.commit()
    return record(skill)


@router.post('/skills/{skill_id}/versions')
def revise_skill(skill_id: str,data: SkillInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    skill=skill_allowed(db.scalar(select(Skill).where(Skill.id==skill_id).with_for_update()),user,db)
    if (skill.public and user.role!='super_admin') or (not skill.public and skill.owner_id!=user.id):
        raise HTTPException(403,'无技能编辑权限')
    data.config.package_metadata=db.get(SkillVersion,skill.current_version_id).config.get('package_metadata',{})
    schema_check(data.config)
    for bid in data.config.base_ids:
        require_base(db,bid,user)
    version=SkillVersion(skill_id=skill.id,creator_id=user.id,config=data.config.model_dump())
    db.add(version)
    db.flush()
    skill.current_version_id=version.id
    skill.name=data.name
    skill.command=data.command
    skill.description=data.description
    audit(db,user,'skill.revise',skill.id,version_id=version.id)
    db.commit()
    return record(version)


@router.get('/skills/{skill_id}/versions')
def skill_versions(skill_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    skill=skill_allowed(db.get(Skill,skill_id),user,db)
    versions=db.scalars(select(SkillVersion).where(SkillVersion.skill_id==skill_id).order_by(SkillVersion.created_at.desc())).all()
    return [record(v) for v in versions if user.role=='super_admin' or skill.owner_id==user.id or v.id==skill.current_version_id]


@router.post('/skills/import')
async def import_skill(file: UploadFile=File(),workflow: str | None=Form(None),user: User=Depends(current_user),db: Session=Depends(get_db)):
    content=await file.read(settings.upload_limit_mb*1024*1024+1)
    if not content or len(content)>settings.upload_limit_mb*1024*1024:
        raise HTTPException(413,'技能包为空或超过上传限制')
    filename=(file.filename or 'skill.zip').replace('\\','/').split('/')[-1]
    data,files=read_skill_package(content,filename,workflow=workflow)
    data.config.package_metadata={**data.config.package_metadata,'file_hash':store(content),'filename':filename,'files':files,'format':'workbench-import-v1'}
    return new_skill(data,user,db,data.config.package_metadata)


@router.post('/skills/import-preview')
async def preview_skill(file: UploadFile=File(),user: User=Depends(current_user)):
    content=await file.read(settings.upload_limit_mb*1024*1024+1)
    if not content or len(content)>settings.upload_limit_mb*1024*1024: raise HTTPException(413,'技能包为空或超过上传限制')
    data,files=read_skill_package(content,file.filename or 'skill.zip',preview=True)
    return {'name':data.name,'description':data.description,'workflow':data.config.workflow if data.config.package_metadata.get('workflow_declared') else None,'files':files,'capabilities':['检索授权知识','读取选定材料','生成文本正文'],'notice':'包内脚本和 Word 模板不会自动执行；Word 模板继承与逐页检查将在后续阶段接入。'}


@router.post('/skills/{skill_id}/clone')
def clone_skill(skill_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    source=skill_allowed(db.get(Skill,skill_id),user,db)
    version=db.get(SkillVersion,source.current_version_id)
    data=SkillInput(name=source.name[:94]+'（个人副本）',description=source.description,command=source.command,public=False,config=version.config)
    result=new_skill(data,user,db,version.config.get('package_metadata',{}))
    return {**result,'config':data.config.model_dump()}


@router.get('/skills/{skill_id}/export')
def export_skill(skill_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    skill=skill_allowed(db.get(Skill,skill_id),user,db)
    config=db.get(SkillVersion,skill.current_version_id).config
    meta=config.get('package_metadata',{})
    original=blob(meta['file_hash']).read_bytes() if meta.get('file_hash') and str(meta.get('filename','')).lower().endswith(('.zip','.skill')) else None
    content=export_skill_package({'name':skill.name,'command':skill.command,'description':skill.description,'config':config},original)
    return Response(content,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="workbench-skill.zip"'})


@router.post('/skills/{skill_id}/publish-request')
def publish_request(skill_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    skill=owned(db.scalar(select(Skill).where(Skill.id==skill_id).with_for_update()),user)
    ensure_active(db,'skill',skill_id)
    if skill.public:
        raise HTTPException(409,'该技能已经是公共技能')
    skill.publication_requested=True
    skill.publication_version_id=skill.current_version_id
    db.commit()
    return record(skill)


@router.post('/skills/{skill_id}/govern')
def govern_skill(skill_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if user.role!='super_admin':
        raise HTTPException(403,'需要管理员权限')
    write_lock(db)
    skill=db.scalar(select(Skill).where(Skill.id==skill_id).with_for_update())
    if not skill:
        raise HTTPException(404,'技能不存在')
    ensure_active(db,'skill',skill_id)
    if data.get('version_id'):
        version=db.get(SkillVersion,data['version_id'])
        if not version or version.skill_id!=skill_id:
            raise HTTPException(422,'版本不属于技能')
        skill.current_version_id=version.id
    if 'public' in data:
        if data['public'] and not skill.public:
            if not skill.publication_requested:
                raise HTTPException(409,'请先提交公共发布申请')
            if skill.publication_version_id!=skill.current_version_id:
                raise HTTPException(409,'申请后技能已有新版本，请重新提交发布申请')
            skill.public=True
            skill.publication_requested=False
            skill.publication_version_id=None
        elif not data['public']:
            skill.enabled=False
    if 'enabled' in data:
        skill.enabled=bool(data['enabled'])
    audit(db,user,'skill.govern',skill.id,settings=data)
    db.commit()
    return record(skill)


@router.delete('/skills/{skill_id}')
def delete_skill(skill_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    skill=skill_allowed(db.get(Skill,skill_id),user,db)
    if skill.public and user.role!='super_admin':
        raise HTTPException(403,'需要管理员权限')
    skill.enabled=False
    audit(db,user,'skill.disable',skill.id)
    db.commit()
    return {'ok':True}


@router.post('/skills/{skill_id}/execute')
def execute_skill(skill_id: str,data: RunInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    skill=skill_allowed(db.get(Skill,skill_id),user,db)
    if is_change_skill(skill):
        raise HTTPException(422,'请从需求包的软需阶段发起「软需变更」任务')
    if not skill.enabled:
        raise HTTPException(409,'技能已禁用')
    version=db.get(SkillVersion,skill.current_version_id)
    workflow=effective_workflow(version.config)
    is_uml=workflow=='uml'
    accepts_requirements=workflow in ('ppt_report','mind_map')
    explicit_materials=is_uml or accepts_requirements
    requirement_ids=[]
    if workflow=='ppt_report':
        requirement_ids=list(dict.fromkeys(data.report_requirement_ids))
    elif data.report_requirement_ids or data.report_audience:
        raise HTTPException(422,'只有一页汇报 PPT 工作流使用汇报需求和受众字段')
    if workflow=='mind_map':
        requirement_ids=list(dict.fromkeys(data.mind_map_requirement_ids))
    elif data.mind_map_requirement_ids:
        raise HTTPException(422,'只有思维导图工作流使用导图需求字段')
    if not data.source_version_ids and not requirement_ids:
        detail='请选择至少一个业务需求或一份已解析文件' if accepts_requirements else 'Work模式必须选择至少一份已解析的业务输入文件，写作样例不能代替业务文件'
        raise HTTPException(422,detail)
    optional_fields={'diagram_types','report_requirement_ids','report_audience','mind_map_requirement_ids'}
    inputs=data.model_dump(exclude={key for key in optional_fields if not getattr(data,key)})
    if accepts_requirements:
        prefix='report' if workflow=='ppt_report' else workflow
        inputs[f'{prefix}_requirement_ids']=requirement_ids
    if explicit_materials:
        inputs['source_version_ids']=list(dict.fromkeys(data.source_version_ids))
        if data.sample_version_ids or data.base_ids or data.word_template_version_id:
            raise HTTPException(422,'此技能仅使用明确选定的资料')
    if is_uml:
        if not data.diagram_types or len(set(data.diagram_types))!=len(data.diagram_types) or any(kind not in DIAGRAM_TYPES for kind in data.diagram_types):
            raise HTTPException(422,'请选择至少一种有效的 UML 图种，每种图只能选择一次')
        if not data.task.strip():
            raise HTTPException(422,'请填写要建模的业务场景或范围')
    elif data.diagram_types:
        raise HTTPException(422,'只有 UML 工作流需要选择图种')
    try:
        validate_schema(inputs,version.config['input_schema'])
    except ValidationError as error:
        raise HTTPException(422,f'输入不符合技能 Schema：{error.message}')
    if set(data.source_version_ids)&set(data.sample_version_ids):
        raise HTTPException(422,'同一文件不能同时作为业务事实和软需写作样例')
    for vid in [*data.source_version_ids,*data.sample_version_ids]:
        source=require_version(db,vid,user)
        if explicit_materials:
            ensure_active(db,'document',source.document_id)
        if source.parse_status!='ready':
            raise HTTPException(409,'输入文档尚未解析完成')
    if data.word_template_version_id:
        template=require_version(db,data.word_template_version_id,user)
        if not template.filename.lower().endswith('.docx') or template.parse_status!='ready':
            raise HTTPException(422,'排版模板应为已解析的 DOCX 文件')
    for bid in ([] if explicit_materials else data.base_ids or version.config.get('base_ids',[])):
        require_base(db,bid,user)
    if accepts_requirements:
        inputs[f'{prefix}_requirement_revisions']={r.id:r.revision for r in selected_requirements(db,user,requirement_ids)}
    if data.requirement_id:
        owned(db.get(Requirement,data.requirement_id),user)
        ensure_active(db,'requirement',data.requirement_id)
        rc=context_for(db,db.get(Requirement,data.requirement_id))
        if not db.scalar(select(Requirement.id).where(Requirement.id==data.requirement_id,requirement_filter())) or rc and rc.kind!='business':
            raise HTTPException(422,'任务只能关联业务需求，请勿选择临时占位或结构化明细')
    if data.conversation_id:
        owned(db.get(Conversation,data.conversation_id),user)
    model=model_config(db)
    strategy='selected-requirements-and-versions' if accepts_requirements else 'selected-versions' if is_uml else 'zh-bm25+rrf-vector-v1'
    run=queue_agent_run(db,user,version,inputs,{'model_config_id':model.id,'model':model.model,'retrieval_strategy':strategy})
    db.commit()
    return record(run)


@router.post('/requirements/{requirement_id}/initialize-tasks')
def initialize_requirement_tasks(requirement_id: str,data: InitializeInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return initialize(db,user,requirement_id,data)


@router.post('/requirements/{requirement_id}/launch-tasks')
def launch_requirement_tasks(requirement_id: str,data: LaunchInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return launch(db,user,requirement_id,data)


@router.post('/requirements/{requirement_id}/packs/{pack_id}/launch-tasks')
def launch_requirement_pack_tasks(requirement_id:str,pack_id:str,data:PackLaunchInput,
                                  user:User=Depends(current_user),db:Session=Depends(get_db)):
    return launch_pack_tasks(db,user,requirement_id,pack_id,data)


@router.post('/requirements/{requirement_id}/packs/{pack_id}/specification-change')
def launch_pack_change(requirement_id:str,pack_id:str,data:ChangeInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return launch_change(db,user,requirement_id,pack_id,data)


@router.get('/agent-runs')
def runs(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return [task_record(db,r,user) for r in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id)).order_by(AgentRun.created_at.desc())).all()]


@router.get('/agent-runs/{run_id}')
def run_detail(run_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    run=owned(db.get(AgentRun,run_id),user)
    ensure_active(db,'agent_run',run_id)
    saved=db.get(DocumentVersion,run.result.get('saved_version_id')) if run.result.get('saved_version_id') else None
    return {**task_record(db,run,user),'document_content':assemble_sections(run.result.get('sections',[])),'deleted_output':bool(saved and is_deleted(db,'document',saved.document_id)),'workflow':effective_workflow(db.get(SkillVersion,run.skill_version_id).config),'steps':[record(s) for s in db.scalars(select(AgentStep).where(AgentStep.run_id==run_id).order_by(AgentStep.created_at)).all()]}


@router.get('/agent-runs/{run_id}/uml/{diagram_type}.svg')
def uml_svg(run_id: str,diagram_type: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    run=owned(db.get(AgentRun,run_id),user)
    ensure_active(db,'agent_run',run_id)
    diagram=next((d for d in run.result.get('uml',{}).get('diagrams',[]) if d['diagram_type']==diagram_type),None)
    if not diagram or not diagram['svg_hash'] or not blob(diagram['svg_hash']).is_file():
        raise HTTPException(404,'没有可下载的 UML 图像')
    return Response(blob(diagram['svg_hash']).read_bytes(),media_type='image/svg+xml',headers={
        'Cache-Control':'private, no-store',
        'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'",
        'X-Content-Type-Options':'nosniff',
    })


@router.get('/agent-runs/{run_id}/mind-map.svg')
def mind_map_svg(run_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    run=owned(db.get(AgentRun,run_id),user)
    ensure_active(db,'agent_run',run_id)
    svg_hash=run.result.get('mind_map',{}).get('svg_hash')
    if run.status!='completed' or not svg_hash or not blob(svg_hash).is_file():
        raise HTTPException(404,'没有可下载的思维导图图像')
    return Response(blob(svg_hash).read_bytes(),media_type='image/svg+xml',headers={
        'Cache-Control':'private, no-store',
        'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'",
        'X-Content-Type-Options':'nosniff',
    })


def completed_report_file(db, user, run_id):
    run=owned(db.get(AgentRun,run_id),user)
    ensure_active(db,'agent_run',run_id)
    file_hash=run.result.get('ppt_report',{}).get('pptx_hash')
    if run.status!='completed' or not file_hash:
        raise HTTPException(404,'没有可下载的一页汇报 PPT')
    source = blob(file_hash)
    if not source.is_file():
        raise HTTPException(404,'没有可下载的一页汇报 PPT')
    return source


@router.get('/agent-runs/{run_id}/report.pptx')
def ppt_report_download(run_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    source = completed_report_file(db, user, run_id)
    return FileResponse(source,media_type=PPTX_MEDIA_TYPE,headers={
        'Content-Disposition':'attachment; filename="one-page-report.pptx"',
        'Cache-Control':'private, no-store',
    })


@router.get('/agent-runs/{run_id}/report-preview.png')
def ppt_report_preview(run_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    source = completed_report_file(db, user, run_id)
    db.rollback()
    return FileResponse(report_preview(source), media_type='image/png', headers={'Cache-Control':'private, no-store'})


@router.post('/agent-runs/{run_id}/resume')
def resume(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    lock_active_run_pack(db,linked_id(db,run),run.inputs)
    if run.status!='awaiting_confirmation' or data.get('approved') is not True:
        raise HTTPException(409,'当前任务不在等待确认或未确认通过')
    try:
        outline=normalize_outline(data.get('outline') if data.get('outline') is not None else run.result.get('outline',[]))
    except ValueError as error:
        raise HTTPException(422,str(error))
    run.inputs={**run.inputs,'_resume':{'approved':True,'outline':outline}}
    run.status='pending'
    job=db.scalar(select(Outbox).where(Outbox.kind=='agent',Outbox.resource_id==run.id).with_for_update())
    job.status='pending'
    job.error=''
    job.lease_token=None
    job.lease_until=None
    run.error=''
    audit(db,user,'agent.confirm_outline',run.id,outline=outline)
    db.commit()
    return record(run)


@router.post('/agent-runs/{run_id}/retry')
def run_retry(run_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    lock_active_run_pack(db,linked_id(db,run),run.inputs)
    if run.status!='failed':
        raise HTTPException(409,'只能重试失败任务')
    job=db.scalar(select(Outbox).where(Outbox.kind=='agent',Outbox.resource_id==run.id).with_for_update())
    job.status='pending'
    job.error=''
    job.lease_token=None
    job.lease_until=None
    run.status='pending'
    run.error=''
    db.commit()
    return record(run)


@router.post('/agent-runs/{run_id}/save')
def save_run(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    linked_requirement(db,run,user)
    if run.status!='completed':
        raise HTTPException(409,'工作流尚未完成')
    if run.inputs.get('_specification_change_mode') in ('manual','partial'):
        raise HTTPException(409,'请在软需文档编辑工作台确认该草稿版本')
    config=db.get(SkillVersion,run.skill_version_id).config
    try:
        validate_schema({key:value for key,value in run.result.items() if key!='editor_draft' and not key.startswith('saved_')},config['output_schema'])
    except ValidationError:
        raise HTTPException(422,'结果不符合技能输出 Schema')
    if config['workflow']=='specification':
        if 'expected_editor_revision' in data and data['expected_editor_revision']!=run.result.get('saved_editor_revision',0):
            raise HTTPException(409,'编辑进度已在其他页面更新，请保留当前内容并重新打开任务后核对')
        previous=require_version(db,run.result['saved_version_id'],user) if run.result.get('saved_version_id') else None
        if previous: ensure_active(db,'document',previous.document_id)
        base_id=str(data.get('base_id',''))
        require_base(db,base_id,user)
        title=str(data.get('title','软件需求说明书')).strip()
        label=str(data.get('label','V1.0')).strip()
        if not title or len(title)>300 or not label or len(label)>80:
            raise HTTPException(422,'标题或版本号无效')
        generated=assemble_sections(run.result.get('sections',[]))
        content=data.get('content',generated)
        if not isinstance(content,str) or not content.strip() or len(content)>2000000:
            raise HTTPException(422,'没有已生成章节')
        if previous and previous.label==label and previous.content==content:
            doc=db.get(Document,previous.document_id)
            if not doc.requirement_id:
                doc.requirement_id=linked_id(db,run)
            run.result={**{key:value for key,value in run.result.items() if key!='editor_draft'},'saved_editor_revision':run.result.get('saved_editor_revision',0)+1}
            db.commit()
            return {**record(previous),'requirement_id':doc.requirement_id}
        folder_id=data.get('folder_id') or None
        if folder_id:
            folder=db.get(Folder,folder_id)
            if not folder or folder.base_id!=base_id:
                raise HTTPException(422,'目录不属于所选知识库')
        baseline=require_version(db,run.inputs['_specification_baseline_id'],user) if run.inputs.get('_specification_baseline_id') else None
        parent=previous or baseline
        if parent:
            doc=db.scalar(select(Document).where(Document.id==parent.document_id).with_for_update())
            ensure_active(db,'document',doc.id)
            if doc.owner_id!=user.id or baseline and doc.requirement_id!=linked_id(db,run):
                raise HTTPException(409,'基线文档的归属已更改')
            if doc.base_id!=base_id:
                raise HTTPException(422,'同一文档的新版本应保存在原知识库')
            if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id==doc.id,DocumentVersion.label==label)):
                raise HTTPException(409,'该版本号已经保存，请填写新的版本号')
            if not doc.requirement_id:
                doc.requirement_id=linked_id(db,run)
        else:
            context_requirement=linked_requirement(db,run,user)
            doc=Document(title=title,owner_id=user.id,base_id=base_id,folder_id=folder_id,kind='specification',requirement_id=context_requirement.id if context_requirement else None)
            db.add(doc)
            db.flush()
        assign_specification(db,run,doc)
        version=DocumentVersion(document_id=doc.id,creator_id=user.id,label=label,parent_id=parent.id if parent else None,filename=title+'.md',file_hash=store(content.encode()),content=content,content_hash=digest(content),blocks=text_blocks(content),parse_status='ready',change_note=str(data.get('change_note','人工编辑后确认版本')),warnings=[run.result.get('review',{}).get('answer','待人工核对')],provenance={'agent_run_id':run.id,'sources':run.citations,'model_trace':run.model_trace,'generated_content_hash':digest(generated),'human_edited':content!=generated,'coverage':run.result.get('review',{}).get('items',[]),'change_baseline_version_id':baseline.id if baseline else None})
        db.add(version)
        db.flush()
        run.result={**{key:value for key,value in run.result.items() if key!='editor_draft'},'saved_editor_revision':run.result.get('saved_editor_revision',0)+1,'saved_version_id':version.id,'saved_version_ids':list(dict.fromkeys([*run.result.get('saved_version_ids',[]),version.id]))}
        link_document(db,run,version.id)
        context_requirement=linked_requirement(db,run,user)
        if context_requirement and context_requirement.state!='published':
            context_requirement.state='specified'
            context_requirement.revision+=1
        audit(db,user,'agent.save_specification',version.id,run_id=run.id)
        db.commit()
        return {**record(version),'requirement_id':doc.requirement_id}
    if config['workflow']=='clarification':
        result=[]
        saved_indices=set(run.result.get('saved_question_indices',[]))
        for i,q in enumerate(run.result.get('clarification',{}).get('questions',[])):
            if i not in data.get('selected_indices',[]) or i in saved_indices:
                continue
            question=Question(owner_id=user.id,requirement_id=linked_id(db,run),description=str(q.get('description','')),category=str(q.get('category','待确认')),reason=str(q.get('reason','')),target=str(q.get('target','')),evidence={'agent_run_id':run.id,'sources':run.citations},status='open')
            if question.description.strip():
                db.add(question)
                db.flush()
                result.append(record(question))
                saved_indices.add(i)
        run.result={**run.result,'saved_question_indices':sorted(saved_indices)}
        db.commit()
        return {'questions':result}
    raise HTTPException(422,'请在需求关联页面人工确认其他类型结果')


@router.post('/agent-runs/{run_id}/save-requirements')
def save_requirements(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    if run.status not in ('completed','awaiting_confirmation') and not (run.inputs.get('_initialization') and 'analysis' in run.result):
        raise HTTPException(409,'任务尚无可确认候选结果')
    saved=[]
    saved_indices=set(run.result.get('saved_requirement_indices',[]))
    items=run.result.get('analysis',{}).get('items',[])
    parent=attach_requirement_context(db,run,user)
    for i,item in enumerate(items):
        if i not in data.get('selected_indices',[]) or i in saved_indices:
            continue
        citation=next((c for c in run.citations if c['citation_id']==item.get('source_citation_id')),None)
        tags=item.get('tags',{})
        # Legacy model results used a flat array. Preserve the labels without guessing categories.
        if isinstance(tags,list) and all(isinstance(value,str) for value in tags):
            tags={'标签':tags} if tags else {}
        if not isinstance(tags,dict) or any(not isinstance(v,list) or any(not isinstance(x,str) for x in v) for v in tags.values()):
            raise HTTPException(422,'候选标签格式无效，请先核对模型结果')
        requirement=Requirement(owner_id=user.id,number=str(item.get('number') or f'AI-{run.id[:8]}-{i+1}'),title=str(item.get('title') or item.get('description','需求候选'))[:300],description=str(item.get('description','')),acceptance=str(item.get('acceptance','')),tags=tags,source_version_id=citation.get('document_version_id') if citation else None,state='confirmed' if data.get('confirm') is True else 'draft')
        db.add(requirement)
        db.flush()
        context_for(db,requirement,'detail',parent.id,run.id)
        audit(db,user,'agent.confirm_requirement_candidate',requirement.id,run_id=run.id,item_index=i,source_citation_id=item.get('source_citation_id'))
        saved.append(requirement_record(db,requirement))
        saved_indices.add(i)
    run.result={**run.result,'saved_requirement_indices':sorted(saved_indices)}
    db.commit()
    return {'requirements':saved}


@router.post('/agent-runs/{run_id}/save-relations')
def save_relations(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    if run.status not in ('completed','awaiting_confirmation') and not (run.inputs.get('_initialization') and 'impact' in run.result):
        raise HTTPException(409,'任务尚无可确认候选结果')
    source=linked_requirement(db,run,user,True)
    target=owned(db.get(Requirement,str(data.get('target_id',''))),user)
    ensure_active(db,'requirement',source.id)
    ensure_active(db,'requirement',target.id)
    if source.id==target.id:
        raise HTTPException(422,'请选择不同的目标需求')
    saved=[]
    indices=set(run.result.get('saved_relation_keys',[]))
    for i,item in enumerate(run.result.get('impact',{}).get('relations',[])):
        key=f'{i}:{target.id}'
        if i not in data.get('selected_indices',[]) or key in indices:
            continue
        relation=Relation(source_id=source.id,target_id=target.id,owner_id=user.id,kind=str(item.get('kind','潜在影响'))[:40],status='candidate',evidence={'agent_run_id':run.id,'candidate':item,'sources':run.citations})
        db.add(relation)
        db.flush()
        saved.append(record(relation))
        indices.add(key)
        audit(db,user,'agent.save_relation_candidate',relation.id,run_id=run.id)
    run.result={**run.result,'saved_relation_keys':sorted(indices)}
    db.commit()
    return {'relations':saved}


def attach_requirement_context(db: Session,run: AgentRun,user: User,requirement_id: str | None=None):
    # Compatibility helper: no task may implicitly create a requirement.
    if requirement_id:
        context=task_context(db,run,True)
        associate_task(db,run,user,requirement_id,context.revision)
    return linked_requirement(db,run,user,required=True)


@router.post('/agent-runs/{run_id}/attach-requirement')
def attach_requirement(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    if not data.get('requirement_id'): raise HTTPException(422,'请在任务详情明确选择业务需求，或新建需求并关联')
    context=task_context(db,run,True)
    associate_task(db,run,user,data['requirement_id'],data.get('expected_revision',context.revision))
    db.commit()
    return {'requirement':record(linked_requirement(db,run,user,True)),'run':task_record(db,run,user)}


@router.get('/requirements/{requirement_id}/candidates')
def requirement_candidates(requirement_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    owned(db.get(Requirement,requirement_id),user)
    ensure_active(db,'requirement',requirement_id)
    result=[]
    for run in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id)).order_by(AgentRun.created_at.desc())).all():
        if linked_id(db,run)==requirement_id and not run.inputs.get('_initialization_run_id'):
            visible={key:value for key,value in run.result.items() if key in ('analysis','clarification','impact') or key.startswith('saved_')}
            result.append({**record(run,('result',)),'result':visible})
    return {'runs':result}


@router.post('/agent-runs/{run_id}/save-questions')
def save_questions(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    if run.status not in ('completed','awaiting_confirmation') and not (run.inputs.get('_initialization') and 'clarification' in run.result):
        raise HTTPException(409,'任务尚无可保存的候选结果')
    requirement=attach_requirement_context(db,run,user)
    saved=set(run.result.get('saved_question_indices',[]))
    result=[]
    for index,item in enumerate(run.result.get('clarification',{}).get('questions',[])):
        if index not in data.get('selected_indices',[]) or index in saved:
            continue
        description=str(item.get('description','')).strip()
        if not description:
            continue
        question=Question(owner_id=user.id,requirement_id=requirement.id,description=description,category=str(item.get('category','待确认')),reason=str(item.get('reason','')),target=str(item.get('target','')),evidence={'agent_run_id':run.id,'sources':run.citations,'candidate':item},status='open')
        db.add(question)
        db.flush()
        result.append(record(question))
        saved.add(index)
    run.result={**run.result,'saved_question_indices':sorted(saved)}
    audit(db,user,'agent.save_questions',run.id,indices=sorted(saved),requirement_id=requirement.id)
    db.commit()
    return {'questions':result}


@router.post('/agent-runs/{run_id}/edit-document')
def assist_document(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    run=owned(db.get(AgentRun,run_id),user)
    ensure_active(db,'agent_run',run_id)
    linked_requirement(db,run,user)
    skill=db.get(SkillVersion,run.skill_version_id)
    if run.status!='completed' or skill.config['workflow']!='specification':
        raise HTTPException(409,'文档生成完成后才可进行 AI 辅助编辑')
    content=data.get('content')
    instruction=data.get('instruction')
    if not isinstance(content,str) or not 1<=len(content)<=200000 or not isinstance(instruction,str) or not 1<=len(instruction.strip())<=3000:
        raise HTTPException(422,'请提供文档正文和编辑要求（正文最多20万字，编辑要求最多3000字）')
    start,end=data.get('selection_start'),data.get('selection_end')
    selected=start is not None or end is not None
    if selected and (not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(content)):
        raise HTTPException(422,'选中的编辑范围无效')
    target=content[start:end] if selected else content
    model_id=run.model_trace.get('model_config_id')
    model=db.get(ModelConfig,model_id) if model_id else None
    if not model or not model.enabled:
        model=model_config(db)
    edited,trace=complete(db,user.id,[{'role':'system','content':SYSTEM_POLICY+'\n'+skill.config['system_prompt']+'\n你正在协助用户编辑需求文档。只返回编辑后的正文，不加解释或代码围栏，不编造业务事实。保留未要求改变的内容、原有引用和待确认事项。'}, {'role':'user','content':json.dumps({'instruction':instruction,'document_untrusted':target,'evidence_untrusted':run.citations},ensure_ascii=False)}],config=model,temperature=skill.config.get('model_parameters',{}).get('temperature',0.2))
    if not edited.strip():
        raise HTTPException(502,'模型返回了空正文，请重试')
    suggestion=content[:start]+edited+content[end:] if selected else edited
    audit(db,user,'document.ai_edit_suggestion',run.id,input_hash=digest(content),output_hash=digest(suggestion),model_trace=trace,selection=[start,end] if selected else None)
    db.commit()
    return {'content':suggestion,'model_trace':trace,'requires_confirmation':True}


@router.put('/agent-runs/{run_id}/document-draft')
def save_editor_progress(run_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    linked_requirement(db,run,user)
    if run.status!='completed' or db.get(SkillVersion,run.skill_version_id).config['workflow']!='specification':
        raise HTTPException(409,'文档生成完成后可保存编辑进度')
    revision=run.result.get('saved_editor_revision',0)
    if 'expected_editor_revision' in data and data['expected_editor_revision']!=revision:
        raise HTTPException(409,'编辑进度已在其他页面更新，当前内容已保留，请重新打开任务核对')
    content=data.get('content')
    if not isinstance(content,str) or len(content)>2000000:
        raise HTTPException(422,'文档内容无效或超过200万字')
    draft={key:str(data.get(key) or '').strip() for key in ('title','label','base_id','folder_id','change_note')}
    if len(draft['title'])>300 or len(draft['label'])>80:
        raise HTTPException(422,'文档名称或版本号过长')
    if draft['base_id']:
        require_base(db,draft['base_id'],user)
    draft['content']=content
    draft['updated_at']=datetime.now(timezone.utc).isoformat()
    run.result={**run.result,'editor_draft':draft,'saved_editor_revision':revision+1}
    db.commit()
    return {'saved':True,'updated_at':draft['updated_at'],'revision':revision+1}
