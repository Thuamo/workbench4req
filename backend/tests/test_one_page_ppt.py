import io
import json
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pymupdf

from app.cli import seed
from app.db import SessionLocal
from app.models import ModelConfig
from app.security import cipher
from app.services.agents import execute
from app.services.files import parse_file, validate
from app.services.ppt_report import A, COMMAND, P, PPTX_MEDIA_TYPE
from app.services import ppt_report_preview
from conftest import ready_source


def test_one_page_report_accepts_requirements_and_files(setup, tmp_path):
    member = setup[0]['member'][0]
    other = setup[0]['other'][0]
    with SessionLocal() as db:
        seed(db)
        db.add(ModelConfig(name='report-fixture', base_url='https://test.invalid/v1', model='fixture', kind='chat',
                           encrypted_key=cipher().encrypt(b'test-only').decode()))
        db.commit()

    def requirement(client, number):
        response = client.post('/requirements', json={'number': number, 'title': '订单取消', 'description': '允许客户在发货前取消订单'})
        assert response.status_code == 200, response.text
        return response.json()['id']

    r1, r2, private = requirement(member, 'REQ-01'), requirement(member, 'REQ-02'), requirement(other, 'REQ-P')
    d1, d2 = ready_source(setup), ready_source(setup)
    items = [skill for skill in member.get('/skills').json() if skill['command'] == COMMAND]
    assert len(items) == 1 and items[0]['public']
    assert '演讲者备注' in items[0]['config']['system_prompt']
    endpoint = '/skills/' + items[0]['id'] + '/execute'
    base = {'task': '汇报订单模块', 'report_audience': '产品评审'}
    assert member.post(endpoint, json=base).status_code == 422
    assert member.post(endpoint, json={**base, 'report_requirement_ids': [private]}).status_code == 404

    for requirements, files, expected in [
        ([r1], [], ['R1']), ([r1, r2], [], ['R1', 'R2']), ([], [d1], ['D1']),
        ([], [d1, d2], ['D1', 'D2']), ([r1], [d1, d2], ['R1', 'D1', 'D2']),
    ]:
        queued = member.post(endpoint, json={**base, 'report_requirement_ids': requirements, 'source_version_ids': files})
        assert queued.status_code == 200, queued.text
        run_id = queued.json()['id']
        preview_url = '/agent-runs/' + run_id + '/report-preview.png'
        assert member.get(preview_url).status_code == 404

        def complete(db, owner, messages, **kwargs):
            request = json.loads(messages[1]['content'])
            assert request['汇报对象'] == '产品评审'
            assert [evidence['key'] for evidence in request['evidence_untrusted']] == expected
            return json.dumps({'headline': '发货前开放订单取消', 'sections': [
                {'heading': '业务目标', 'detail': '允许客户在发货前取消订单。', 'citations': expected}],
                'speaker_notes': ['按资料确认适用范围。']}), {}

        with patch('app.services.ppt_report.complete', side_effect=complete):
            execute(run_id)
        task = member.get('/processing-tasks/' + run_id).json()
        assert task['status'] == 'completed' and task['business_completed'] is True
        assert [source['key'] for source in task['result']['ppt_report']['sources']] == expected
        url = '/agent-runs/' + run_id + '/report.pptx'
        pptx = member.get(url)
        assert pptx.status_code == 200 and pptx.headers['content-type'] == PPTX_MEDIA_TYPE
        assert other.get(url).status_code in (403, 404)
        preview = tmp_path/'preview.png'
        preview.write_bytes(pymupdf.Pixmap(pymupdf.csRGB, 1, 1, b'\xff\xff\xff', False).tobytes('png'))
        with patch('app.routes.workflows.report_preview', return_value=preview) as render:
            assert other.get(preview_url).status_code == 404
            render.assert_not_called()
            image = member.get(preview_url)
            assert image.status_code == 200 and image.headers['content-type'] == 'image/png'
            assert image.headers['cache-control'] == 'private, no-store'
            assert image.content == preview.read_bytes()
            assert render.call_args.args[0].read_bytes() == pptx.content
        with zipfile.ZipFile(io.BytesIO(pptx.content)) as archive:
            presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
            assert len(presentation.findall(f'{P}sldIdLst/{P}sldId')) == 1
            slide = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            text = [node.text for node in slide.iter(A + 't') if node.text]
            assert text == ['发货前开放订单取消', '业务目标', '允许客户在发货前取消订单。']
            notes = ET.fromstring(archive.read('ppt/notesSlides/notesSlide1.xml'))
            assert '按资料确认适用范围。' in [node.text for node in notes.iter(A + 't')]

    uploaded = tmp_path / validate(pptx.content, 'meeting.pptx')
    uploaded.write_bytes(pptx.content)
    parsed = parse_file(uploaded, '.pptx')
    assert parsed['blocks'][0]['locator'].startswith('第1张幻灯片')
    assert parsed['blocks'][0]['text'] == '发货前开放订单取消'


def test_rendered_preview_is_reused_for_the_same_pptx(tmp_path, monkeypatch):
    source = tmp_path/'file-hash'
    source.write_bytes(b'PPTX file bytes')
    monkeypatch.setattr(ppt_report_preview.settings, 'storage_dir', tmp_path)
    png = pymupdf.Pixmap(pymupdf.csRGB, 1, 1, b'\xff\xff\xff', False).tobytes('png')

    def export(input_file, output_file):
        assert input_file.suffix == '.pptx'
        assert input_file.read_bytes() == source.read_bytes()
        output_file.write_bytes(png)

    with patch.object(ppt_report_preview, '_export_first_slide', side_effect=export) as render:
        first = ppt_report_preview.report_preview(source)
        assert first.read_bytes() == png
        assert ppt_report_preview.report_preview(source) == first
        render.assert_called_once()
