import json
from unittest.mock import patch

import pytest

from app.db import SessionLocal
from app.models import ModelConfig
from app.security import cipher
from app.services.agents import execute
from app.services.files import store
from app.services.mind_map import COMMAND, checked_map, plantuml_source
from conftest import ready_source


SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Rules</text></svg>'


def test_map_checks_sources_depth_and_escapes_labels():
    leaf = {'label': '规则\n@endmindmap <img:example>', 'citations': ['D1'], 'status': 'pending'}
    mind_map, count = checked_map(json.dumps({'title': '订单', 'branches': [leaf]}), {'D1'})
    assert count == 2
    source = plantuml_source(mind_map)
    assert source.count('@endmindmap') == 1
    assert '<img:' not in source and '【待确认】' in source
    with pytest.raises(ValueError, match='来源编号'):
        checked_map(json.dumps({'title': '订单', 'branches': [leaf]}), {'R1'})
    deep = leaf
    for _ in range(4):
        deep = {'label': '分类', 'children': [deep]}
    with pytest.raises(ValueError, match='层级'):
        checked_map(json.dumps({'title': '订单', 'branches': [deep]}), {'D1'})


def test_mind_map_skill_runs_on_requirements_and_documents(setup):
    member, other = setup[0]['member'][0], setup[0]['other'][0]
    with SessionLocal() as db:
        db.add(ModelConfig(name='map-fixture', base_url='https://test.invalid/v1', model='fixture', kind='chat',
                           encrypted_key=cipher().encrypt(b'test-only').decode()))
        db.commit()
    requirement = member.post('/requirements', json={'number': 'M-1', 'title': '订单规则', 'description': '发货前允许取消'}).json()
    private = other.post('/requirements', json={'number': 'M-P', 'title': '其他需求'}).json()['id']
    file_id = ready_source(setup)
    skills = [skill for skill in member.get('/skills').json() if skill['command'] == COMMAND]
    assert len(skills) == 1 and skills[0]['public']
    assert '多份文件' in skills[0]['description'] and '验收标准' in skills[0]['config']['system_prompt']
    skill_id = skills[0]['id']
    endpoint = f'/skills/{skill_id}/execute'
    base = {'task': '梳理取消规则'}
    assert member.post(endpoint, json=base).status_code == 422
    assert member.post(endpoint, json={**base, 'mind_map_requirement_ids': [private]}).status_code == 404

    launched = member.post(f"/requirements/{requirement['id']}/launch-tasks", json={'skill_ids': [skill_id]})
    assert launched.status_code == 200, launched.text
    run_id = launched.json()['task_ids'][f'skill:{skill_id}']
    run = member.get('/agent-runs/' + run_id).json()
    assert run['inputs']['mind_map_requirement_revisions'] == {requirement['id']: requirement['revision']}
    assert not run['inputs']['source_version_ids']

    for ids, versions, expected in [([], [file_id], ['D1']), ([requirement['id']], [file_id], ['R1', 'D1'])]:
        queued = member.post(endpoint, json={**base, 'mind_map_requirement_ids': ids, 'source_version_ids': versions})
        assert queued.status_code == 200, queued.text
        run_id = queued.json()['id']
        url = f'/agent-runs/{run_id}/mind-map.svg'
        assert member.get(url).status_code == 404

        def complete(db, owner, messages, **kwargs):
            request = json.loads(messages[1]['content'])
            assert request['梳理范围与重点'] == base['task']
            assert [source['key'] for source in request['evidence_untrusted']] == expected
            return json.dumps({'title': '取消订单', 'branches': [{'label': '适用条件', 'status': 'pending',
                              'detail': '状态需核对', 'citations': expected}]}), {}

        with patch('app.services.mind_map.complete', side_effect=complete), \
                patch('app.services.mind_map.render', return_value=(store(SVG), '')):
            execute(run_id)
        task = member.get('/processing-tasks/' + run_id).json()
        assert task['status'] == 'completed' and task['business_completed'] is True
        result = task['result']['mind_map']
        assert result['node_count'] == 2 and result['branches'][0]['status'] == 'pending'
        assert [source['key'] for source in result['sources']] == expected
        assert all('text' not in source for source in result['sources'])
        image = member.get(url)
        assert image.status_code == 200 and image.content == SVG
        assert image.headers['content-type'] == 'image/svg+xml'
        assert image.headers['cache-control'] == 'private, no-store'
        assert other.get(url).status_code == 404
