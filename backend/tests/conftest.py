import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

Path('test-results').mkdir(exist_ok=True)
os.environ['DATABASE_URL']='sqlite:///./test-results/api-tests.db'
os.environ['STORAGE_DIR']='./test-results/storage'
os.environ['ENCRYPTION_KEY']=Fernet.generate_key().decode()
from app.main import app
from app.db import Base, engine, SessionLocal
from app.models import User, KnowledgeBase
from app.cli import seed


@pytest.fixture()
def setup():
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        Base.metadata.drop_all(connection)
        Base.metadata.create_all(connection)
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.commit()
    with SessionLocal() as db:
        seed(db)
        base_id=db.query(KnowledgeBase).first().id
    clients={}
    for name,role in [('member','requirement_member'),('other','requirement_member'),('review_a','reviewer'),('review_b','reviewer'),('admin','super_admin')]:
        client=TestClient(app)
        token=client.get('/auth/csrf').json()['csrf_token']
        client.headers.update({'X-CSRF-Token':token,'Origin':'http://localhost:3000'})
        response=client.post('/auth/register',json={'username':name,'display_name':name,'password':'Test-only_password123','confirm_password':'Test-only_password123'})
        assert response.status_code==200,response.text
        account_id=response.json()['id']
        with SessionLocal() as db:
            db.get(User,account_id).role=role
            db.commit()
        assert client.post('/auth/login',json={'username':name,'password':'Test-only_password123'}).status_code==200
        clients[name]=(client,account_id)
    yield clients,base_id
    for client,_ in clients.values():
        client.close()


def ready_source(setup,who='member'):
    from app.models import Document,DocumentVersion
    from app.services.files import store
    with SessionLocal() as db:
        owner=setup[0][who][1]
        doc=Document(owner_id=owner,base_id=setup[1],title='必选业务输入')
        db.add(doc);db.flush()
        version=DocumentVersion(document_id=doc.id,creator_id=owner,label='V1.0',filename='input.txt',file_hash=store(b'work source fixture'),content='测试业务证据',parse_status='ready')
        db.add(version);db.flush();vid=version.id;db.commit()
    return vid
