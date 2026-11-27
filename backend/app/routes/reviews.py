from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import ReviewTask, ReviewRequest, DocumentVersion, Document, User, Audit
from ..security import current_user, reviewer
from ..schemas import Decision, BatchDecision
from ..serialize import record
from ..services.review import decide, batch_decide

router=APIRouter(tags=['审核'])


@router.get('/reviewers')
def reviewers(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return [record(u) for u in db.scalars(select(User).where(User.enabled.is_(True),User.role.in_(['reviewer','super_admin']),User.id!=user.id)).all()]


@router.get('/reviews')
def reviews(scope: str | None=None,user: User=Depends(current_user),db: Session=Depends(get_db)):
    scope=scope or ('all' if user.role=='super_admin' else 'mine')
    if scope not in ('mine','submitted','done','history','pending','all'):
        raise HTTPException(422,'审核范围无效')
    if scope in ('pending','all') and user.role!='super_admin':
        raise HTTPException(403,'全部审核任务仅管理员可查看')
    rows=[]
    for req in db.scalars(select(ReviewRequest).order_by(ReviewRequest.created_at.desc())).all():
        tasks=db.scalars(select(ReviewTask).where(ReviewTask.request_id==req.id)).all()
        assigned=any(t.reviewer_id==user.id for t in tasks)
        if scope=='pending' and req.status not in ('pending','in_review'):
            continue
        if scope=='done' and not any(t.reviewer_id==user.id and t.decision in ('approved','returned') for t in tasks):
            continue
        if scope=='submitted' and req.submitter_id!=user.id:
            continue
        if scope=='mine' and not assigned:
            continue
        if scope not in ('submitted','mine') and not (assigned or req.submitter_id==user.id or user.role=='super_admin'):
            continue
        version=db.get(DocumentVersion,req.version_id)
        doc=db.get(Document,version.document_id)
        rows.append({**record(req),'document':record(doc),'version':record(version,('content','blocks')),'tasks':[{**record(t),'reviewer_name':db.get(User,t.reviewer_id).display_name} for t in tasks]})
    return rows


@router.get('/reviews/{request_id}')
def review_detail(request_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    rows=reviews('history',user,db)
    row=next((r for r in rows if r['id']==request_id),None)
    if not row:
        raise HTTPException(404,'审核申请未授权')
    row['version']=record(db.get(DocumentVersion,row['version_id']))
    import difflib
    from ..models import Question
    version=db.get(DocumentVersion,row['version_id'])
    parent=db.get(DocumentVersion,version.parent_id) if version.parent_id else None
    before=parent.content.splitlines() if parent else [];after=version.content.splitlines()
    changes=[{'kind':k,'before':before[a:b],'after':after[c:d]} for k,a,b,c,d in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes() if k!='equal']
    doc=db.get(Document,version.document_id)
    unresolved=db.scalar(select(func.count()).select_from(Question).where(Question.requirement_id==doc.requirement_id,Question.owner_id==doc.owner_id,Question.status.in_(['open','answered']))) if doc.requirement_id else 0
    changed_sources=0
    for source in version.provenance.get('sources',[]):
        v=db.get(DocumentVersion,source.get('document_version_id')) if source.get('document_version_id') else None
        d=db.get(Document,v.document_id) if v else None
        if d and d.current_version_id and d.current_version_id!=v.id and source.get('role')!='writing_sample':changed_sources+=1
    row['review_summary']={'parent_label':parent.label if parent else None,'change_groups':changes[:100],'truncated':len(changes)>100,'unresolved_questions':unresolved,'changed_source_count':changed_sources,'structure_check':version.provenance.get('structure_check',{})}
    task_ids=[t['id'] for t in row['tasks']]
    row['events']=[record(a) for a in db.scalars(select(Audit).where(Audit.resource_id.in_(task_ids+[row['version_id']]))).all()]
    return row


@router.post('/review-tasks/{task_id}/decision')
def decision(task_id: str,data: Decision,user: User=Depends(reviewer),db: Session=Depends(get_db)):
    return record(decide(db,user,task_id,data.decision,data.comment))


@router.post('/review-tasks/batch-decision')
def decisions(data: BatchDecision,user: User=Depends(reviewer),db: Session=Depends(get_db)):
    return batch_decide(db,user,data)
