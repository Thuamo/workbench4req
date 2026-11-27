from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import ReviewRequest,ReviewTask,DocumentVersion,Outbox,Audit
from app.worker import process_one
from test_qa_and_batch_review import source


def pending(setup,number):
    clients,_=setup;v=source(setup,number)
    req=clients['member'][0].post('/versions/'+v['id']+'/submit',json={'reviewer_ids':[clients['review_a'][1],clients['review_b'][1]]})
    assert req.status_code==200,req.text
    return clients['member'][0].get('/reviews/'+req.json()['id']).json()


def payload(setup,rows,who='review_a',decision='approved',comment='批量核对通过'):
    uid=setup[0][who][1]
    return {'decision':decision,'comment':comment,'items':[{'task_id':next(t['id'] for t in row['tasks'] if t['reviewer_id']==uid),'locked_hash':row['locked_hash']} for row in rows]}


def count(db,model):return db.scalar(select(func.count()).select_from(model))


def test_batch_approval_respects_cosignature_and_publishes_once(setup):
    clients,_=setup;rows=[pending(setup,'50059'),pending(setup,'50060')]
    first=clients['review_a'][0].post('/review-tasks/batch-decision',json=payload(setup,rows))
    assert first.status_code==200,first.text
    assert first.json()['decided']==2 and all(r['status']=='in_review' for r in first.json()['results'])
    with SessionLocal() as db:assert count(db,Outbox)==0
    final=clients['review_b'][0].post('/review-tasks/batch-decision',json=payload(setup,rows,'review_b'))
    assert final.status_code==200 and all(r['status']=='approved' and r['publish_status']=='queued' for r in final.json()['results'])
    with SessionLocal() as db:
        assert count(db,Outbox)==2
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='review.batch_decide'))==2
        assert all(t.comment=='批量核对通过' for t in db.scalars(select(ReviewTask)).all())
    assert process_one() and process_one() and not process_one()
    result=clients['member'][0].get('/search',params={'q':'互斥校验'}).json()
    assert {r['document_version_id'] for r in result}=={r['version_id'] for r in rows}
    assert clients['review_b'][0].post('/review-tasks/batch-decision',json=payload(setup,rows,'review_b')).status_code==409
    with SessionLocal() as db:assert count(db,Outbox)==2


def test_batch_return_requires_reason_and_cancels_other_pending_tasks(setup):
    clients,_=setup;rows=[pending(setup,'50059'),pending(setup,'50060')];data=payload(setup,rows,decision='returned',comment=' ')
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json=data).status_code==422
    data['comment']='接口异常处理未明确，请补充'
    response=clients['review_a'][0].post('/review-tasks/batch-decision',json=data)
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        assert count(db,Outbox)==0
        for req in db.scalars(select(ReviewRequest)).all():assert req.status=='returned'
        tasks=db.scalars(select(ReviewTask)).all()
        assert sum(t.decision=='returned' for t in tasks)==2 and sum(t.decision=='cancelled' for t in tasks)==2
    assert clients['review_b'][0].post('/review-tasks/batch-decision',json=payload(setup,rows,'review_b')).status_code==409


def test_batch_checks_assignment_snapshot_duplicates_and_rolls_back_every_item(setup):
    clients,_=setup;rows=[pending(setup,'50059'),pending(setup,'50060')];data=payload(setup,rows)
    assert clients['member'][0].post('/review-tasks/batch-decision',json=data).status_code==403
    assert clients['admin'][0].post('/review-tasks/batch-decision',json=data).status_code==404
    foreign=payload(setup,[rows[1]],'review_b')['items'][0]
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json={**data,'items':[data['items'][0],foreign]}).status_code==404
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json={**data,'items':[]}).status_code==422
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json={**data,'items':data['items']*26}).status_code==422
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json={**data,'items':[data['items'][0],data['items'][0]]}).status_code==422
    bad={**data,'items':[data['items'][0],{**data['items'][1],'locked_hash':'0'*64}]}
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json=bad).status_code==409
    with SessionLocal() as db:
        assert all(t.decision=='pending' for t in db.scalars(select(ReviewTask)).all())
        assert not db.scalar(select(Audit.id).where(Audit.action=='review.decide'))
    t=data['items'][1]['task_id']
    assert clients['review_a'][0].post('/review-tasks/'+t+'/decision',json={'decision':'approved'}).status_code==200
    assert clients['review_a'][0].post('/review-tasks/batch-decision',json=data).status_code==409
    with SessionLocal() as db:
        assert db.get(ReviewTask,data['items'][0]['task_id']).decision=='pending'
        assert count(db,Outbox)==0


def test_concurrent_batch_last_signatures_create_one_job_per_document(setup):
    clients,_=setup;rows=[pending(setup,'50059'),pending(setup,'50060')]
    def sign(who):return clients[who][0].post('/review-tasks/batch-decision',json=payload(setup,rows,who)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(sign,['review_a','review_b']))
    assert results==[200,200]
    with SessionLocal() as db:
        assert count(db,Outbox)==2 and all(r.status=='approved' for r in db.scalars(select(ReviewRequest)).all())


def test_legacy_self_assigned_review_cannot_be_signed_in_batch_or_individually(setup):
    clients,_=setup;row=pending(setup,'50059');data=payload(setup,[row]);tid=data['items'][0]['task_id']
    with SessionLocal() as db:
        # Simulate a legacy invalid assignment, without changing file content.
        db.get(ReviewTask,tid).reviewer_id=clients['admin'][1]
        db.get(ReviewRequest,row['id']).submitter_id=clients['admin'][1];db.commit()
    assert clients['admin'][0].post('/review-tasks/batch-decision',json=data).status_code==403
    assert clients['admin'][0].post('/review-tasks/'+tid+'/decision',json={'decision':'approved'}).status_code==403
    with SessionLocal() as db:assert db.get(ReviewTask,tid).decision=='pending'
    with SessionLocal() as db:
        db.get(ReviewRequest,row['id']).submitter_id=clients['member'][1]
        db.get(DocumentVersion,row['version_id']).creator_id=clients['admin'][1];db.commit()
    assert clients['admin'][0].post('/review-tasks/batch-decision',json=data).status_code==403
