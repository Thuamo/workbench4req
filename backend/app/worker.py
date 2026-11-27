import time, logging
from datetime import timedelta
from threading import Event, Thread
from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import OperationalError
from .db import SessionLocal
from .models import Outbox, DocumentVersion, AgentRun, now, uid
from .security import write_lock
from .services.publishing import parse_version, build_and_publish
from .services.agents import execute
from .db_errors import sqlite_busy

logging.basicConfig(level=logging.INFO)
JOB_LEASE = timedelta(hours=1)


def claim_job() -> tuple | None:
    with SessionLocal() as db:
        write_lock(db)
        job=db.scalar(select(Outbox).where(or_(Outbox.status=='pending',and_(Outbox.status=='running',Outbox.lease_until<now()))).order_by(Outbox.created_at).with_for_update(skip_locked=True).limit(1))
        if not job:
            db.rollback()
            return None
        job.status='running'
        job.attempts+=1
        job.lease_token=uid()
        job.lease_until=now()+JOB_LEASE
        job_id,token,kind,resource_id=job.id,job.lease_token,job.kind,job.resource_id
        db.commit()
        return job_id,token,kind,resource_id


def renew_agent_lease(job_id, token, finished):
    while not finished.wait(60):
        try:
            with SessionLocal() as db:
                renewed=db.execute(update(Outbox).where(
                    Outbox.id==job_id, Outbox.lease_token==token, Outbox.status=='running',
                ).values(lease_until=now()+JOB_LEASE))
                db.commit()
                if not renewed.rowcount:
                    return
        except OperationalError:
            logging.exception('Could not renew agent job lease: %s', job_id)


def process_one() -> bool:
    try:
        claimed=claim_job()
    except OperationalError as error:
        if not sqlite_busy(error):
            raise
        logging.warning('Database busy; worker will retry without consuming a job')
        return False
    if not claimed:
        return False
    job_id,token,kind,resource_id=claimed
    try:
        if kind=='agent':
            # Allow long model reads while the worker still owns this job.
            finished=Event()
            renewal=Thread(target=renew_agent_lease,args=(job_id,token,finished),daemon=True)
            renewal.start()
            try:
                execute(resource_id)
            finally:
                finished.set()
                renewal.join()
        else:
            with SessionLocal() as db:
                if kind=='parse':
                    parse_version(db,resource_id)
                elif kind in ('publish','reindex'):
                    build_and_publish(db,resource_id,reindex=kind=='reindex')
                else:
                    raise RuntimeError('未知任务类型')
        with SessionLocal() as db:
            db.execute(update(Outbox).where(Outbox.id==job_id,Outbox.lease_token==token).values(status='completed',error=''))
            db.commit()
    except Exception as error:
        logging.exception('Job failed: %s %s',kind,resource_id)
        with SessionLocal() as db:
            job=db.get(Outbox,job_id)
            if job.lease_token==token:
                job.status='failed'
                job.error=str(error)[:2000]
                if kind=='parse':
                    db.get(DocumentVersion,resource_id).parse_status='failed'
                elif kind=='agent':
                    run=db.get(AgentRun,resource_id)
                    run.status='failed'
                    run.error=str(error)[:2000]
                db.commit()
    return True


if __name__=='__main__':
    while True:
        if not process_one():
            time.sleep(2)
