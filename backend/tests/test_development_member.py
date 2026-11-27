from unittest.mock import patch

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AgentRun, Document, KnowledgeBase, Relation, Requirement, Skill
from test_chat_modes_and_reset import model
from test_qa_and_batch_review import QaClient, source
from test_workbench import publish, upload


def test_development_member_permissions(setup):
    clients, base_id = setup
    admin = clients['admin'][0]
    member, owner_id = clients['member']
    dev, dev_id = clients['other']
    password = 'Test-only_password123'
    created = admin.post('/admin/users', json={
        'username': 'developer', 'display_name': '开发人员', 'password': password,
        'confirm_password': password, 'role': 'development_member',
    })
    assert created.status_code == 200, created.text
    assert created.json()['role'] == 'development_member'
    assert admin.patch(f'/admin/users/{dev_id}', json={'role': 'development_member'}).status_code == 200
    assert dev.get('/auth/me').status_code == 401
    assert dev.post('/auth/login', json={'username': 'other', 'password': password}).status_code == 200
    assert dev.get('/auth/me').json()['role'] == 'development_member'

    private = source(setup)
    formal = upload(setup, text='贷后报告线上化，新增互斥校验规则。')
    publish(setup, formal)
    with SessionLocal() as db:
        restricted = KnowledgeBase(name='未授权库', public=False)
        requirement = Requirement(owner_id=owner_id, number='REQ-1', title='贷款报告', source_version_id=private['id'])
        related = Requirement(owner_id=owner_id, number='REQ-2', title='提交校验')
        db.add_all([restricted, requirement, related])
        db.flush()
        db.get(Document, formal['document_id']).requirement_id = requirement.id
        skill = db.scalar(select(Skill).where(Skill.command == '/关联分析'))
        linked = AgentRun(owner_id=owner_id, skill_version_id=skill.current_version_id, status='completed',
                          inputs={'requirement_id': requirement.id, 'task': '私有提示词', 'source_version_ids': [private['id']]},
                          result={'analysis': {'answer': '需求分析', 'items': [{'description': '互斥校验', 'evidence': '私有证据'}]},
                                  'sections': ['私有草稿']}, model_trace={'private': True})
        unlinked = AgentRun(owner_id=owner_id, skill_version_id=skill.current_version_id, inputs={'task': '未关联任务'})
        relation = Relation(source_id=requirement.id, target_id=related.id, owner_id=owner_id, kind='depends_on',
                            evidence={'reason': '依赖规则', 'private': '私有证据'})
        db.add_all([linked, unlinked, relation])
        db.commit()
        rid, linked_id, unlinked_id = requirement.id, linked.id, unlinked.id
        related_id, relation_id, skill_id = related.id, relation.id, skill.id

    base_ids = {row['id'] for row in dev.get('/knowledge-bases').json()}
    assert base_id in base_ids and restricted.id not in base_ids
    assert dev.get(f'/knowledge-bases/{base_id}/folders').status_code == 200
    formal_path = f"/documents/{formal['document_id']}/versions/{formal['id']}"
    assert dev.get(formal_path).status_code == 200
    assert dev.get(f"/documents/{private['document_id']}/versions/{private['id']}").status_code == 404
    assert dev.get(f"/versions/{formal['id']}/download").status_code == 200

    rows = {row['id']: row for row in dev.get('/requirements').json()}
    assert rows[rid]['source_version_id'] is None
    assert rows[rid]['task_count'] == 1 and rows[rid]['document_count'] == 1
    workspace = dev.get(f'/requirements/{rid}/workspace').json()
    assert workspace['source'] is None and workspace['task_initialization'] is None
    assert {row['id'] for row in workspace['runs']} == {linked_id}
    assert {row['id'] for row in workspace['documents']} == {formal['document_id']}
    task = dev.get(f'/processing-tasks/{linked_id}').json()
    assert task['result'] == {'analysis': {'answer': '需求分析', 'items': [{'description': '互斥校验'}]}}
    assert task['documents'] == [] and task['model_trace'] == {}
    assert '私有提示词' not in str(task)
    assert dev.get(f'/processing-tasks/{unlinked_id}').status_code == 404
    relations = dev.get('/relations').json()
    assert [(row['id'], row['target_id']) for row in relations] == [(relation_id, related_id)]
    assert '私有证据' not in str(relations)

    model()
    conversation = dev.post('/conversations').json()['id']
    messages = f'/conversations/{conversation}/messages'
    with patch('app.routes.chat.httpx.AsyncClient', QaClient):
        answer = dev.post(messages, json={'content': '互斥校验规则是什么', 'scopes': ['formal']})
    assert answer.status_code == 200, answer.text
    assert dev.get(messages).json()[-1]['citations']
    assert member.get(messages).status_code == 404
    assert dev.post(messages, json={'content': '运行技能', 'skill_id': skill_id}).status_code == 403

    for method, path in [
        ('POST', '/requirements'), ('PATCH', f'/requirements/{rid}'),
        ('POST', f'/requirements/{rid}/initialize-tasks'), ('PATCH', f'/relations/{relation_id}'),
        ('POST', '/documents/upload'), ('POST', f"/versions/{formal['id']}/comments"),
        ('GET', '/clarification/tasks'), ('GET', '/skills'), ('GET', '/admin/users'),
    ]:
        response = dev.request(method, path, json={})
        assert response.status_code == 403, (method, path, response.text)
