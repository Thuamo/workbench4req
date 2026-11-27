import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.main import app
from app import cli
from app.db import Base
from app.models import User
from app.security import verify


def test_six_character_registration_login_change_and_admin_creation(setup):
    clients,_=setup
    with TestClient(app) as member:
        member.headers['X-CSRF-Token']=member.get('/auth/csrf').json()['csrf_token']
        account={'username':'six_character_user','display_name':'六位密码测试','password':'Abc123','confirm_password':'Abc123'}
        assert member.post('/auth/register',json={**account,'password':'Abc12','confirm_password':'Abc12'}).status_code==422
        assert member.post('/auth/register',json={**account,'confirm_password':'Abc124'}).status_code==422
        created=member.post('/auth/register',json=account)
        assert created.status_code==200,created.text
        assert 'password' not in created.json() and 'password_hash' not in created.json()
        assert member.post('/auth/login',json={'username':account['username'],'password':'Abc123'}).status_code==200
        assert member.post('/auth/password',json={'current_password':'Abc123','password':'Abc12'}).status_code==422
        assert member.post('/auth/password',json={'current_password':'Abc123','password':'Xyz789'}).status_code==200
        assert member.get('/auth/me').status_code==401
        assert member.post('/auth/login',json={'username':account['username'],'password':'Abc123'}).status_code==401
        assert member.post('/auth/login',json={'username':account['username'],'password':'Xyz789'}).status_code==200
    admin=clients['admin'][0]
    created=admin.post('/admin/users',json={**account,'username':'admin_created_six'})
    assert created.status_code==200,created.text
    assert admin.post('/auth/login',json={'username':'admin','password':'Test-only_password123'}).status_code==200


@pytest.mark.parametrize('password,accepted',[('Abc12',False),('Abc123',True)])
def test_first_admin_cli_password_boundary(tmp_path,monkeypatch,password,accepted):
    engine=create_engine('sqlite:///'+str(tmp_path/'bootstrap.db'))
    Base.metadata.create_all(engine)
    session=sessionmaker(engine)
    monkeypatch.setattr(cli,'SessionLocal',session)
    monkeypatch.setattr('sys.argv',['app.cli','init-admin','--username','bootstrap_admin'])
    monkeypatch.setattr(cli.getpass,'getpass',lambda prompt:password)
    if accepted:
        cli.main()
    else:
        with pytest.raises(SystemExit):
            cli.main()
    with session() as db:
        account=db.scalar(select(User).where(User.role=='super_admin'))
        if accepted:
            assert account and verify(password,account.password_hash)
            assert account.password_hash!=password
        else:
            assert account is None
    engine.dispose()
