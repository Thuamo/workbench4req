from collections import Counter
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User, ModelConfig, Audit, Outbox, Setting, AuthSession, KnowledgeBase, Document, DocumentVersion, Requirement, Relation, ClarificationTask, ReviewTask, ReviewRequest, Conversation, AgentRun, Notification, Metric
from ..security import current_user, admin, cipher, hasher, audit, base_allowed, write_lock
from ..schemas import AdminRegister, ModelInput
from ..serialize import record
from ..models import Skill, SkillVersion, USER_ROLES

from ..services.deletion import active_filter, requirement_filter, ensure_active

router=APIRouter(tags=['管理与工作台'])

@router.get('/admin/retrieval-status')
def retrieval_status(user:User=Depends(admin),db:Session=Depends(get_db)):
    from ..models import IndexBuild
    models=db.scalars(select(ModelConfig).where(ModelConfig.kind=='embedding',ModelConfig.enabled.is_(True))).all()
    ids={m.id for m in models}
    docs=db.scalars(select(Document).where(Document.current_index_id.is_not(None),active_filter('document',Document.id))).all()
    compatible=sum(bool((build:=db.get(IndexBuild,d.current_index_id)) and build.status=='ready' and build.model_config_id in ids) for d in docs)
    return {'strategy':'shared-qa-v2','embedding_enabled':bool(models),'formal_index_count':len(docs),'compatible_index_count':compatible,'message':'问答与技能任务共用授权和检索逻辑。'+('向量配置已启用；不兼容的正式索引需重建。' if models else '尚未配置向量模型，当前使用关键词与章节匹配；请配置供应商支持的 Embeddings 模型后重建正式索引。')}


@router.get('/admin/skill-requests')
def skill_requests(user: User=Depends(admin),db: Session=Depends(get_db)):
    return [{**record(s),'config':db.get(SkillVersion,s.publication_version_id).config} for s in db.scalars(select(Skill).where(Skill.publication_requested.is_(True))).all() if s.publication_version_id]


@router.get('/admin/users')
def users(user: User=Depends(admin),db: Session=Depends(get_db)):
    return [record(u) for u in db.scalars(select(User)).all()]


@router.post('/admin/users')
def create_user(data: AdminRegister,user: User=Depends(admin),db: Session=Depends(get_db)):
    if db.scalar(select(User.id).where(User.username==data.username)):
        raise HTTPException(409,'用户名已存在')
    account=User(username=data.username,display_name=data.display_name,password_hash=hasher.hash(data.password),role=data.role)
    db.add(account)
    db.flush()
    audit(db,user,'admin.user_create',account.id,role=account.role)
    db.commit()
    return record(account)


@router.patch('/admin/users/{user_id}')
def update_user(user_id: str,data: dict,user: User=Depends(admin),db: Session=Depends(get_db)):
    write_lock(db)
    account=db.scalar(select(User).where(User.id==user_id).with_for_update())
    if not account:
        raise HTTPException(404,'用户不存在')
    role=data.get('role',account.role)
    enabled=data.get('enabled',account.enabled)
    if role not in USER_ROLES or not isinstance(enabled,bool):
        raise HTTPException(422,'角色或状态无效')
    if account.role=='super_admin' and (role!='super_admin' or not enabled):
        count=db.scalar(select(func.count()).select_from(User).where(User.role=='super_admin',User.enabled.is_(True)))
        if count<=1:
            raise HTTPException(409,'不能停用或降级最后一名管理员')
    account.role=role
    account.enabled=enabled
    db.execute(delete(AuthSession).where(AuthSession.user_id==user_id))
    audit(db,user,'admin.user_edit',account.id,role=role,enabled=enabled)
    db.commit()
    return record(account)


@router.post('/admin/users/{user_id}/reset-password')
def reset_password(user_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    write_lock(db)
    account=db.scalar(select(User).where(User.id==user_id).with_for_update())
    if not account: raise HTTPException(404,'用户不存在')
    account.password_hash=hasher.hash('mima123')
    db.execute(delete(AuthSession).where(AuthSession.user_id==user_id))
    audit(db,user,'admin.password_reset',account.id)
    db.commit()
    return {'ok':True,'message':'密码已重置，该用户需重新登录'}


@router.get('/admin/models')
def models(user: User=Depends(admin),db: Session=Depends(get_db)):
    return [record(m) for m in db.scalars(select(ModelConfig).where(
        active_filter('model_config',ModelConfig.id)).order_by(ModelConfig.created_at.desc())).all()]


@router.post('/admin/models')
def create_model(data: ModelInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    if len(data.base_url)>500 or len(data.model)>200 or len(data.name)>100:
        raise HTTPException(422,'模型配置字段过长')
    config=ModelConfig(name=data.name,base_url=data.base_url.rstrip('/'),model=data.model,kind=data.kind,encrypted_key=cipher().encrypt(data.api_key.encode()).decode())
    db.add(config)
    db.flush()
    audit(db,user,'model.configure',config.id,model=data.model,kind=data.kind)
    db.commit()
    return record(config)


@router.post('/admin/models/{model_id}/disable')
def disable_model(model_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    write_lock(db)
    config=db.scalar(select(ModelConfig).where(ModelConfig.id==model_id).with_for_update())
    if not config:
        raise HTTPException(404,'模型不存在')
    ensure_active(db,'model_config',config.id)
    config.enabled=False
    audit(db,user,'model.disable',config.id)
    db.commit()
    return record(config)


@router.get('/admin/audit')
def audits(user: User=Depends(admin),db: Session=Depends(get_db)):
    return [record(a) for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(300)).all()]


@router.get('/admin/jobs')
def jobs(user: User=Depends(admin),db: Session=Depends(get_db)):
    return [record(j) for j in db.scalars(select(Outbox).order_by(Outbox.created_at.desc()).limit(100)).all()]


@router.post('/admin/jobs/{job_id}/retry')
def retry_job(job_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    write_lock(db)
    job=db.get(Outbox,job_id)
    if not job or job.status!='failed':
        raise HTTPException(409,'只能重试失败任务')
    if job.kind=='agent':
        from ..services.processing_tasks import linked_id
        from ..services.requirement_packs import lock_active_run_pack
        ensure_active(db,'agent_run',job.resource_id)
        run=db.get(AgentRun,job.resource_id)
        lock_active_run_pack(db,linked_id(db,run),run.inputs)
    else:
        version=db.get(DocumentVersion,job.resource_id)
        if version: ensure_active(db,'document',version.document_id)
    job.status='pending'
    if job.kind=='agent':
        db.get(AgentRun,job.resource_id).status='pending'
    if job.kind=='parse':
        db.get(DocumentVersion,job.resource_id).parse_status='pending'
    audit(db,user,'job.retry',job.id)
    db.commit()
    return record(job)


@router.get('/settings/{key}')
def setting(key: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if key not in ('tags','scoring'):
        raise HTTPException(404,'配置不存在')
    item=db.scalar(select(Setting).where(Setting.key==key))
    return record(item)


@router.put('/settings/{key}')
def set_setting(key: str,data: dict,user: User=Depends(admin),db: Session=Depends(get_db)):
    if key not in ('tags','scoring'):
        raise HTTPException(404,'配置不存在')
    if key=='scoring' and (not all(k in data for k in ('version','interface_weight','rule_weight','module_weight')) or any(not isinstance(data[k],(int,float)) or not 0<=data[k]<=100 for k in ('interface_weight','rule_weight','module_weight'))):
        raise HTTPException(422,'评分规则必须含版本及非负权重')
    item=db.scalar(select(Setting).where(Setting.key==key))
    if not item:
        item=Setting(key=key,value=data)
        db.add(item)
    else:
        item.value=data
    audit(db,user,'setting.update',key,value=data)
    db.commit()
    return record(item)


@router.get('/notifications')
def notifications(user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..services.journey import destination_for
    return [{**record(n),'destination':destination_for(db,user,n.resource_id)} for n in db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(50)).all()]


@router.post('/notifications/{notification_id}/read')
def notification_read(notification_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    n=db.get(Notification,notification_id)
    if not n or n.user_id!=user.id:
        raise HTTPException(404,'通知不存在')
    n.read=True
    db.commit()
    return record(n)


@router.get('/dashboard')
def dashboard(user: User=Depends(current_user),db: Session=Depends(get_db)):
    bases=[b.id for b in db.scalars(select(KnowledgeBase)).all() if base_allowed(b,user)]
    documents=db.scalars(select(Document).where(Document.base_id.in_(bases),active_filter('document',Document.id))).all()
    official=[d for d in documents if d.current_version_id]
    own=[d for d in documents if d.owner_id==user.id]
    reqs=db.scalars(select(Requirement).where(Requirement.owner_id==user.id,requirement_filter())).all()
    tasks=db.scalars(select(ClarificationTask).where(active_filter('clarification_task',ClarificationTask.id))).all()
    requests=db.scalars(select(ReviewRequest).where(ReviewRequest.submitter_id==user.id)).all()
    own_relations=db.scalars(select(Relation).where(Relation.owner_id==user.id,active_filter('relation',Relation.id))).all()
    generated=db.scalars(select(Document).where(active_filter('document',Document.id),Document.owner_id==user.id,Document.kind=='specification')).all()
    metrics=db.scalars(select(Metric).where(Metric.requirement_id.in_([r.id for r in reqs])).order_by(Metric.created_at)).all()
    latest={m.requirement_id:m for m in metrics}
    trend=Counter(d.created_at.strftime('%Y-%m') for d in official)
    active_versions=[db.get(DocumentVersion,d.current_version_id) for d in official]
    return {'counts':{'知识库':len(bases),'正式知识文件':len(official),'结构化需求':len(reqs),'待澄清任务':sum(t.status in ('pending','in_progress') for t in tasks),'已生成软需':len(generated),'待审核文件':sum(r.status in ('pending','in_review') for r in requests),'已发布软需':sum(d.kind=='specification' for d in official),'需求关联':len(own_relations)},'charts':{'需求类型':dict(Counter(tag for r in reqs for tag in r.tags.get('需求类型',[]))),'复杂度':dict(Counter(m.values.get('复杂度','未度量') for m in latest.values())),'生命周期':dict(Counter(r.state for r in reqs)),'澄清进度':dict(Counter(t.status for t in tasks)),'软需进度':dict(Counter(str(t.fields.get('软需进展') or '未填写') for t in tasks)),'审核状态':dict(Counter(r.status for r in requests)),'知识库增长':dict(sorted(trend.items())),'版本更新':dict(Counter(v.created_at.strftime('%Y-%m') for v in active_versions))},'recent':{'documents':[record(d) for d in sorted(own,key=lambda d:d.created_at,reverse=True)[:5]],'reviews':[record(r) for r in requests[-5:]],'conversations':[record(c) for c in db.scalars(select(Conversation).where(Conversation.owner_id==user.id).order_by(Conversation.created_at.desc()).limit(5)).all()]}}
