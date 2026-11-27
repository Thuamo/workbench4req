import io
from unittest.mock import patch

from fastapi import HTTPException
from openpyxl import Workbook


def workbook(columns, rows, invalid_second_sheet=False):
    wb = Workbook()
    wb.active.append(columns)
    for row in rows:
        wb.active.append(row)
    if invalid_second_sheet:
        sheet = wb.create_sheet('错误表')
        sheet.append(['需求编号', '需求名称', '需求名称'])
        sheet.append(['BAD', '错误', '重复'])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def upload(client, content, **data):
    return client.post('/clarification/import', data=data, files={'file': ('计划.xlsx', content)})


def preview(client, content):
    response = client.post('/clarification/import-preview', files={'file': ('计划.xlsx', content)})
    assert response.status_code == 200, response.text
    return response.json()


def confirmed_upload(client, content):
    return upload(client, content, expected_snapshot=preview(client, content)['snapshot'])


def test_incremental_import_and_undo_preserve_links_history_and_other_users(setup):
    clients, _ = setup
    member, other = clients['member'][0], clients['other'][0]
    requirement = member.post('/requirements', json={'number': 'RM_00053681', 'title': '已有需求', 'tags': {'系统': ['信贷']}}).json()
    original = member.post('/clarification/tasks', json={
        'status': 'in_progress',
        'fields': {'需求编号': '53681', '需求名称': '旧计划', '备注': '人工备注', '工作量': 5},
    }).json()
    manual = member.post('/clarification/tasks', json={'fields': {'需求编号': 'MANUAL', '需求名称': '手工计划'}}).json()
    other_task = other.post('/clarification/tasks', json={'fields': {'需求编号': '53681', '需求名称': '他人计划'}}).json()
    question = member.post('/clarification/questions', json={
        'description': '原计划澄清问题', 'category': '规则', 'task_id': original['id'], 'requirement_id': requirement['id'],
    }).json()

    content = workbook(['需求编号', '需求名称', '备注', '工作量', '澄清结果', '新字段'], [
        ['rm-053681', '更新计划', None, 0, '澄清结束', '新数据'],
        ['R-2', '新计划', '新增备注'],
        ['DUP', '重复编号A'],
        ['DUP', '重复编号B'],
        [None, '没有编号'],
    ])
    checked = preview(member, content)
    assert [checked[key] for key in ('added', 'updated', 'unchanged', 'conflicts')] == [1, 1, 0, 3]
    assert checked['rows'][0]['changed_fields'] == ['需求名称', '工作量', '澄清结果', '新字段']
    assert [row['row'] for row in checked['rows'] if row['action'] == 'conflict'] == [4, 5, 6]
    assert {task['id'] for task in member.get('/clarification/tasks').json()} == {original['id'], manual['id'], other_task['id']}
    response = upload(member, content, expected_snapshot=checked['snapshot'])
    assert response.status_code == 200, response.text
    result = response.json()
    rows = {task['id']: task for task in member.get('/clarification/tasks').json()}
    updated = rows[original['id']]
    added = next(task for task in rows.values() if task['fields']['需求编号'] == 'R-2')
    assert len(rows) == 4 and rows[manual['id']]['fields'] == manual['fields']
    assert rows[other_task['id']]['fields'] == other_task['fields']
    assert updated['revision'] == 2 and updated['requirement_id'] == requirement['id'] and updated['status'] == 'completed'
    assert updated['fields'] == {
        '需求编号': '53681', '需求名称': '更新计划', '备注': '人工备注', '工作量': 0, '澄清结果': '澄清结束', '新字段': '新数据',
    }
    assert member.get('/clarification/questions').json()[0]['id'] == question['id']
    assert member.get('/clarification/questions').json()[0]['task_id'] == original['id']
    assert len(member.get('/clarification/tasks/'+original['id']+'/history').json()) == 2
    assert member.get('/clarification/imports').json()[0]['id'] == result['batch_id']
    assert other.get('/clarification/imports').json() == []
    undo = '/clarification/imports/'+result['batch_id']+'/undo'
    assert other.post(undo).status_code == 404
    assert member.post(undo).status_code == 200
    assert member.post(undo).status_code == 200

    restored = {task['id']: task for task in member.get('/clarification/tasks').json()}
    assert added['id'] not in restored
    assert restored[original['id']]['fields'] == original['fields']
    assert restored[original['id']]['status'] == 'in_progress' and restored[original['id']]['revision'] == 3
    assert restored[original['id']]['requirement_id'] == requirement['id']
    assert len(member.get('/clarification/tasks/'+original['id']+'/history').json()) == 3
    assert len(member.get('/clarification/tasks/'+added['id']+'/history').json()) == 1
    assert member.get('/clarification/imports').json()[0]['undone'] is True
    assert confirmed_upload(member, content).json()['added'] == 1


def test_confirmation_is_bound_to_file_user_and_current_ledger(setup):
    member, other = setup[0]['member'][0], setup[0]['other'][0]
    data = workbook(['需求编号', '需求名称'], [['R-1', '原任务']])
    replacement = workbook(['需求编号', '需求名称'], [['R-1', '新任务']])
    assert upload(member, data).status_code == 409
    checked = preview(member, data)
    assert upload(other, data, expected_snapshot=checked['snapshot']).status_code == 409
    assert upload(member, replacement, expected_snapshot=checked['snapshot']).status_code == 409
    assert upload(member, data, expected_snapshot=checked['snapshot']).status_code == 200
    old = member.get('/clarification/tasks').json()[0]
    repeated = confirmed_upload(member, data).json()
    assert repeated['unchanged'] == 1 and repeated['batch_id'] is None
    checked = preview(member, replacement)
    response = member.patch('/clarification/tasks/'+old['id'], json={
        'fields': {**old['fields'], '需求名称': '预览后的人工修改'},
        'expected_revision': old['revision'], 'status': old['status'], 'requirement_id': old['requirement_id'],
    })
    assert response.status_code == 200, response.text
    stale = upload(member, replacement, expected_snapshot=checked['snapshot'])
    assert stale.status_code == 409 and '重新预览' in stale.text
    assert member.get('/clarification/tasks').json()[0]['fields']['需求名称'] == '预览后的人工修改'
    assert confirmed_upload(member, replacement).json()['updated'] == 1
    assert member.get('/clarification/tasks').json()[0]['id'] == old['id']


def test_ambiguous_existing_rows_and_requirements_are_conflicts(setup):
    member = setup[0]['member'][0]
    for text in ('甲', '乙'):
        assert member.post('/clarification/tasks', json={'fields': {'需求编号': 'DUP', '需求名称': text}}).status_code == 200
        assert member.post('/requirements', json={'number': 'RM_00053682', 'title': text, 'tags': {'项目': [text]}}).status_code == 200
    data = workbook(['需求编号', '需求名称'], [['DUP', '台账重复'], ['53682', '需求重复'], ['UNIQUE', '可导入']])
    checked = preview(member, data)
    assert [row['reason'] for row in checked['rows'][:2]] == ['本人台账已有多条同编号计划', '编号匹配多个业务需求，请人工核对']
    assert confirmed_upload(member, data).json()['added'] == 1
    assert len(member.get('/clarification/tasks').json()) == 3


def test_batch_undo_refuses_later_edits_or_question_links(setup):
    member = setup[0]['member'][0]
    content = workbook(['需求编号', '需求名称'], [['R-1', '计划一'], ['R-2', '计划二']])
    result = confirmed_upload(member, content).json()
    before = member.get('/clarification/tasks').json()
    task = before[0]
    question = member.post('/clarification/questions', json={'description': '新增后产生的澄清问题', 'category': '规则', 'task_id': task['id']})
    assert question.status_code == 200, question.text
    path = '/clarification/imports/'+result['batch_id']+'/undo'
    assert member.post(path).status_code == 409
    assert member.get('/clarification/tasks').json() == before
    question_id = question.json()['id']
    assert member.request('DELETE', '/records/question/'+question_id, json={'confirm': True}).status_code == 200
    response = member.patch('/clarification/tasks/'+task['id'], json={
        'fields': {**task['fields'], '备注': '导入后的修改'},
        'expected_revision': task['revision'], 'status': task['status'], 'requirement_id': task['requirement_id'],
    })
    assert response.status_code == 200, response.text
    stale = member.post(path)
    assert stale.status_code == 409 and '已修改' in stale.text
    assert len(member.get('/clarification/tasks').json()) == 2


def test_invalid_sheet_and_transaction_failure_preserve_original_rows(setup):
    member = setup[0]['member'][0]
    valid = workbook(['需求编号', '需求名称', '旧列'], [['OLD', '原计划', '原内容']])
    assert confirmed_upload(member, valid).status_code == 200
    original = member.get('/clarification/tasks').json()
    snapshot = preview(member, valid)['snapshot']
    for content in (
        workbook(['需求编号', '需求名称'], []),
        workbook(['错误表头'], [['错误内容']]),
        workbook(['需求编号', '需求名称'], [['NEW', '不可部分导入']], True),
    ):
        assert member.post('/clarification/import-preview', files={'file': ('计划.xlsx', content)}).status_code == 422
        assert upload(member, content, expected_snapshot=snapshot).status_code == 422
        assert member.get('/clarification/tasks').json() == original

    next_file = workbook(['需求编号', '需求名称', '新列'], [['OLD', '更新计划', '写入失败'], ['NEW', '新增计划', '写入失败']])
    snapshot = preview(member, next_file)['snapshot']
    with patch('app.services.ledger.audit', side_effect=HTTPException(422, 'test-only import failure after writes')):
        assert upload(member, next_file, expected_snapshot=snapshot).status_code == 422
    assert member.get('/clarification/tasks').json() == original
    assert len(member.get('/clarification/tasks/'+original[0]['id']+'/history').json()) == 1
    assert member.get('/clarification/columns').json()['columns'] == ['需求编号', '需求名称', '旧列']
    assert len(member.get('/requirements').json()) == 1

