import sqlite3
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import DocumentVersion, Outbox
from app.worker import process_one


def test_database_lock_is_json_503_and_worker_recovers(setup):
    clients,base=setup
    member=clients['member'][0]
    uploaded=member.post('/documents/upload',data={'title':'锁恢复测试','base_id':base,'label':'V1'},files={'file':('lock.md','测试锁释放后继续解析'.encode(),'text/markdown')})
    assert uploaded.status_code==200,uploaded.text
    version_id=uploaded.json()['id']
    path=Path(make_url(settings.database_url).database)
    connection=sqlite3.connect(str(path),timeout=1,isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        registration=member.post('/auth/register',json={'username':'lock_test_user','display_name':'锁测试','password':'Abc123','confirm_password':'Abc123'})
        login=member.post('/auth/login',json={'username':'member','password':'Test-only_password123'})
        for response in [registration,login]:
            assert response.status_code==503,response.text
            assert response.headers['content-type'].startswith('application/json')
            assert '数据库' in response.json()['detail']
            assert response.headers['retry-after']=='2'
        assert process_one() is False
        with SessionLocal() as db:
            assert db.scalar(select(Outbox).where(Outbox.kind=='parse',Outbox.resource_id==version_id)).status=='pending'
    finally:
        connection.rollback()
        connection.close()
    assert process_one() is True
    with SessionLocal() as db:
        assert db.get(DocumentVersion,version_id).parse_status=='ready'
        assert db.scalar(select(Outbox).where(Outbox.kind=='parse',Outbox.resource_id==version_id)).status=='completed'
    assert member.post('/auth/login',json={'username':'member','password':'Test-only_password123'}).status_code==200
