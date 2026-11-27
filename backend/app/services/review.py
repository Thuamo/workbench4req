from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import Document, DocumentVersion, ReviewRequest, ReviewTask, User, Outbox, Notification, now, uid
from .deletion import ensure_active
from ..security import require_version, require_base, audit, digest, write_lock


def submit_review(db: Session, user: User, version_id: str, reviewer_ids: list[str], note: str, commit: bool=True):
    if commit: write_lock(db)
    preview=require_version(db,version_id,user)
    db.scalar(select(Document).where(Document.id==preview.document_id).with_for_update())
    version=db.scalar(select(DocumentVersion).where(DocumentVersion.id==version_id).with_for_update())
    ensure_active(db,'document',version.document_id)
    require_version(db,version_id,user)
    if version.creator_id!=user.id and user.role!='super_admin':
        raise HTTPException(403,'只有该修订创建人可以提交')
    doc=db.get(Document,version.document_id)
    if doc.kind=='specification' and doc.requirement_id:
        from ..models import RequirementPackSpecification
        from .requirement_packs import lock_active_run_pack
        home=db.scalar(select(RequirementPackSpecification.pack_id).where(
            RequirementPackSpecification.document_id==doc.id))
        lock_active_run_pack(db,doc.requirement_id,{'_requirement_pack_id':home})
    require_base(db,doc.base_id,user)
    if version.status!='draft' or version.parse_status!='ready' or not version.content.strip():
        raise HTTPException(409,'只能提交解析完成的非空草稿')
    ids=set(reviewer_ids)
    if not ids or user.id in ids or version.creator_id in ids:
        raise HTTPException(422,'至少选择一名审核员，提交人和版本创建人不能审核本人内容')
    people=db.scalars(select(User).where(User.id.in_(ids),User.enabled.is_(True),User.role.in_(['reviewer','super_admin']))).all()
    if len(people)!=len(ids):
        raise HTTPException(422,'包含无效审核员')
    version.content_hash=digest(version.content)
    version.review_status='pending'
    version.status='pending_review'
    request=ReviewRequest(version_id=version.id,submitter_id=user.id,locked_hash=version.content_hash,note=note)
    db.add(request)
    db.flush()
    for person in people:
        db.add(ReviewTask(request_id=request.id,reviewer_id=person.id))
        db.add(Notification(user_id=person.id,message=f'待审核：{doc.title} {version.label}',resource_id=request.id))
    audit(db,user,'review.submit',version.id,reviewer_ids=sorted(ids),hash=version.content_hash)
    if commit: db.commit()
    return request


def batch_submit(db: Session, user: User, data):
    if len(set(data.version_ids))!=len(data.version_ids):
        raise HTTPException(422,'不能重复选择同一版本')
    write_lock(db)
    requests=[]
    try:
        doc_ids=set()
        for vid in sorted(data.version_ids):
            version=None
            version=require_version(db,vid,user)
            doc_ids.add(version.document_id)
        # Stable document lock order also protects batches on PostgreSQL.
        db.scalars(select(Document).where(Document.id.in_(doc_ids)).order_by(Document.id).with_for_update()).all()
        for vid in sorted(data.version_ids):
            version=None
            version=require_version(db,vid,user)
            # Refresh under the same writer lock used by edit/submit.
            db.refresh(version)
            if data.expected_pack_id:
                from ..models import RequirementPackSpecification
                doc=db.get(Document,version.document_id)
                home=db.scalar(select(RequirementPackSpecification.pack_id).where(
                    RequirementPackSpecification.document_id==doc.id))
                if doc.kind!='specification' or (home or doc.requirement_id)!=data.expected_pack_id:
                    raise HTTPException(409,'所选软需版本不属于当前需求包')
            if vid in data.expected_revisions and version.revision!=data.expected_revisions[vid]:
                raise HTTPException(409,'文档已被修改，请刷新后重新选择')
            requests.append(submit_review(db,user,vid,data.reviewer_ids,data.note,commit=False))
        db.commit()
    except HTTPException as error:
        filename=version.filename if version else vid
        db.rollback()
        raise HTTPException(error.status_code,{'message':'批量提交未完成，所有文件均未提交','version_id':vid,'filename':filename,'reason':error.detail}) from error
    return {'submitted':len(requests),'requests':[{'id':r.id,'version_id':r.version_id} for r in requests]}


def decide(db: Session,user: User,task_id: str,decision: str,comment: str,commit: bool=True):
    if commit: write_lock(db)
    task=db.get(ReviewTask,task_id)
    if not task or task.reviewer_id!=user.id:
        raise HTTPException(404,'任务不存在或未分配给您')
    request=db.scalar(select(ReviewRequest).where(ReviewRequest.id==task.request_id).with_for_update().execution_options(populate_existing=True))
    db.refresh(task)
    version=db.get(DocumentVersion,request.version_id)
    ensure_active(db,'document',version.document_id)
    if user.id in (request.submitter_id,version.creator_id):
        raise HTTPException(403,'提交人或版本创建人不能审核本人内容')
    if decision not in ('approved','returned'): raise HTTPException(422,'审核决定无效')
    if request.status not in ('pending','in_review') or task.decision!='pending':
        raise HTTPException(409,'本轮已结束或已作出决定')
    if digest(version.content)!=request.locked_hash:
        raise HTTPException(409,'审核内容哈希不匹配')
    if decision=='returned' and not comment.strip():
        raise HTTPException(422,'退回必须填写原因')
    task.decision=decision
    task.comment=comment.strip()
    task.decided_at=now()
    db.flush()
    tasks=db.scalars(select(ReviewTask).where(ReviewTask.request_id==request.id)).all()
    if decision=='returned':
        request.status='returned'
        version.review_status='returned'
        for other in tasks:
            if other.decision=='pending':
                other.decision='cancelled'
        # Returned submission remains immutable; requester creates a new revision.
    elif all(t.decision=='approved' for t in tasks):
        request.status='approved'
        version.review_status='approved'
        version.status='approved'
        version.publish_status='queued'
        db.add(Outbox(kind='publish',resource_id=version.id))
    else:
        request.status='in_review'
        version.review_status='in_review'
        version.status='in_review'
    audit(db,user,'review.decide',task.id,decision=decision,comment=comment,request_id=request.id)
    db.add(Notification(user_id=request.submitter_id,message=f'审核更新：{request.status}',resource_id=request.id))
    if commit: db.commit()
    return request


def batch_decide(db: Session,user: User,data):
    ids=[item.task_id for item in data.items]
    if len(ids)!=len(set(ids)): raise HTTPException(422,'不能重复选择同一个审核任务')
    if data.decision=='returned' and not data.comment.strip(): raise HTTPException(422,'批量退回必须填写原因')
    write_lock(db)
    results=[];task_id='';label=''
    try:
        request_ids=set()
        for task_id in sorted(ids):
            label=task_id
            task=db.get(ReviewTask,task_id)
            if not task or task.reviewer_id!=user.id: raise HTTPException(404,'任务不存在或未分配给您')
            request_ids.add(task.request_id)
        # Batch and individual decisions share request locks; stable ordering
        # prevents parallel batches from acquiring the same requests in reverse.
        requests=db.scalars(select(ReviewRequest).where(ReviewRequest.id.in_(request_ids)).order_by(ReviewRequest.id).with_for_update().execution_options(populate_existing=True)).all()
        by_request={r.id:r for r in requests}
        for item in sorted(data.items,key=lambda item:item.task_id):
            task_id=item.task_id;label=task_id
            task=db.get(ReviewTask,task_id);db.refresh(task)
            request=by_request[task.request_id]
            version=db.get(DocumentVersion,request.version_id)
            label=version.filename+' · '+version.label
            if item.locked_hash!=request.locked_hash: raise HTTPException(409,'审核版本已变化，请重新核对')
            result=decide(db,user,task_id,data.decision,data.comment,commit=False)
            results.append({'task_id':task_id,'request_id':result.id,'status':result.status,'publish_status':version.publish_status})
        audit(db,user,'review.batch_decide',uid(),task_ids=ids,decision=data.decision,comment=data.comment.strip(),count=len(results))
        db.commit()
    except HTTPException as error:
        db.rollback()
        raise HTTPException(error.status_code,{'message':'本次批量审核未应用，所有已选任务均未变更','reason':error.detail,'task_id':task_id,'filename':label}) from error
    return {'decided':len(results),'decision':data.decision,'results':results}
