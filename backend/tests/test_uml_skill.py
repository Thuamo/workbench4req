import json
from unittest.mock import call, patch

from app.cli import seed
from app.db import SessionLocal
from app.models import ModelConfig
from app.security import cipher
from app.services.agents import execute
from app.services.files import store
from app.services.uml import COMMAND
from conftest import ready_source


def test_uml_skill_uses_only_selected_versions_and_protects_svg(setup):
    member = setup[0]['member'][0]
    other = setup[0]['other'][0]
    source_id = ready_source(setup)
    other_id = ready_source(setup, 'other')
    with SessionLocal() as db:
        seed(db)
        db.add(ModelConfig(name='uml-fixture', base_url='https://test.invalid/v1', model='test-only',
                           kind='chat', encrypted_key=cipher().encrypt(b'test-only').decode()))
        db.commit()

    entries = [skill for skill in member.get('/skills').json() if skill['command'] == COMMAND]
    assert len(entries) == 1 and entries[0]['public'] and entries[0]['config']['workflow'] == 'uml'
    choices = member.get('/uml/diagram-types').json()
    assert len(choices) == 15
    assert {'id': 'flowchart', 'label': '流程图', 'approximate': False} in choices
    assert {'id': 'activity', 'label': '活动图', 'approximate': False} in choices
    endpoint = '/skills/' + entries[0]['id'] + '/execute'
    payload = {'task': '核对订单取消场景', 'source_version_ids': [source_id]}
    assert member.post(endpoint, json=payload).status_code == 422
    assert member.post(endpoint, json={**payload, 'diagram_types': ['unknown']}).status_code == 422
    assert member.post(endpoint, json={**payload, 'source_version_ids': [other_id], 'diagram_types': ['sequence']}).status_code in (403, 404)
    queued = member.post(endpoint, json={**payload, 'diagram_types': ['sequence', 'state', 'flowchart']})
    assert queued.status_code == 200, queued.text
    run_id = queued.json()['id']

    flowchart = '@startuml\nstart\n:提交订单;\nif (校验通过?) then (是)\n:生成订单;\nelse (否)\n:返回错误;\nendif\nstop\n@enduml\n'

    def complete(db, owner, messages, **kwargs):
        request = json.loads(messages[1]['content'])
        assert [item['version_id'] for item in request['evidence_untrusted']] == [source_id]
        assert [item['diagram_type'] for item in request['diagram_types']] == ['sequence', 'state', 'flowchart']
        assert '判断' in request['diagram_types'][-1]['guidance']
        return json.dumps({'diagrams': [
            {'diagram_type': 'state', 'title': '订单状态', 'notes': ['缺少状态转换证据']},
            {'diagram_type': 'sequence', 'title': '取消订单', 'citations': ['D1', 'D2'],
             'source': '@startuml\r\nClient -> Service: cancel()\r\n@enduml'},
            {'diagram_type': 'flowchart', 'title': '提交订单流程', 'citations': ['D1'], 'source': flowchart},
        ]}), {}

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="10">cancel</text></svg>'
    svg_hash = store(svg)
    with patch('app.services.uml.complete', side_effect=complete), patch('app.services.uml.render', return_value=(svg_hash, '')) as render:
        execute(run_id)
    assert render.call_args_list == [call('@startuml\nClient -> Service: cancel()\n@enduml\n', 'sequence'), call(flowchart, 'flowchart')]
    task = member.get('/processing-tasks/' + run_id).json()
    assert task['status'] == 'completed' and task['business_completed'] is True
    sequence, state, flow = task['result']['uml']['diagrams']
    assert sequence['diagram_type'] == 'sequence' and sequence['citations'] == ['D1']
    assert state['source'] == '' and state['notes'] == ['缺少状态转换证据']
    assert flow['label'] == '流程图' and flow['source'] == flowchart

    image = '/agent-runs/' + run_id + '/uml/sequence.svg'
    response = member.get(image)
    assert response.status_code == 200 and response.content == svg
    assert response.headers['content-type'] == 'image/svg+xml'
    assert other.get(image).status_code in (403, 404)
    assert member.get('/agent-runs/' + run_id + '/uml/flowchart.svg').content == svg
    assert member.get('/agent-runs/' + run_id + '/uml/state.svg').status_code == 404
