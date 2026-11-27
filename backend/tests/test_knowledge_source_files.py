import io
import json

import pymupdf as fitz
from docx import Document as WordDocument
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models import DEVELOPMENT_MEMBER, Document, DocumentVersion, KnowledgeBase, User
from app.security import digest
from app.services import knowledge_consolidation
from app.services.files import blob, parse_file, store


def workbook_bytes():
    workbook = Workbook()
    workbook.active.title = '能力地图'
    for row in range(1, 53):
        workbook.active.append([row, f'能力 {row}'])
    workbook.create_sheet('依赖规则').append(['规则 X', '适用于授信'])
    result = io.BytesIO()
    workbook.save(result)
    return result.getvalue()


def png_bytes():
    image = fitz.Pixmap(fitz.csRGB, 2, 2, bytes([65, 124, 208]*4), False)
    return image.tobytes('png')


def word_bytes():
    doc = WordDocument()
    paragraph = doc.add_paragraph('图前文字')
    paragraph.add_run().add_picture(io.BytesIO(png_bytes()))
    paragraph.add_run('图后文字')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '依赖规则'
    result = io.BytesIO()
    doc.save(result)
    return result.getvalue()


def pdf_bytes():
    with fitz.open() as pdf:
        for text in ('Page 1', 'Page 2'):
            page = pdf.new_page()
            page.insert_text((20, 30), text)
            page.insert_image(fitz.Rect(20, 50, 60, 90), stream=png_bytes())
        return pdf.tobytes()


def asset(db, base_id, owner, title, filename, data, published=False):
    document = Document(base_id=base_id, owner_id=owner, title=title)
    db.add(document)
    db.flush()
    file_hash = store(data)
    parsed = parse_file(blob(file_hash), '.'+filename.rsplit('.', 1)[-1])
    version = DocumentVersion(document_id=document.id, creator_id=owner, filename=filename, label='V1.0',
                              file_hash=file_hash, parse_status='ready', content_hash=digest(parsed['content']), **parsed)
    db.add(version)
    db.flush()
    if published:
        version.status = version.publish_status = 'published'
        document.current_version_id = version.id
    return version.id


def test_spreadsheet_and_word_preview_enforce_version_permissions(setup):
    clients, base_id = setup
    admin, owner = clients['admin']
    reader, reader_id = clients['other']
    with SessionLocal() as db:
        db.get(User, reader_id).role = DEVELOPMENT_MEMBER
        sheet_id = asset(db, base_id, owner, '执行能力地图', 'map.xlsx', workbook_bytes(), published=True)
        word_id = asset(db, base_id, owner, '带图说明书', 'guide.docx', word_bytes())
        pdf_id = asset(db, base_id, owner, 'PDF 示例', 'guide.pdf', pdf_bytes(), published=True)
        assert db.get(DocumentVersion, sheet_id).blocks[-1]['locator'] == '依赖规则!第1行'
        db.commit()

    table = f'/versions/{sheet_id}/source-preview'
    result = reader.get(table)
    assert result.status_code == 200, result.text
    assert result.json()['sheets'] == ['能力地图', '依赖规则']
    assert result.json()['has_more'] is True
    assert reader.get(table, params={'offset': 50}).json()['rows'][-1] == ['52', '能力 52']
    assert reader.get(table, params={'sheet': 1}).json()['rows'] == [['规则 X', '适用于授信']]
    word = f'/versions/{word_id}/source-preview'
    assert reader.get(word).status_code == 404
    assert reader.get(word+'/image/0').status_code == 404
    preview = admin.get(word)
    assert preview.status_code == 200, preview.text
    assert preview.json()['blocks'][0]['parts'] == ['图前文字', 0, '图后文字']
    image = admin.get(word+'/image/0')
    assert image.headers['content-type'] == 'image/png'
    assert image.content == png_bytes()
    pdf = f'/versions/{pdf_id}/source-preview'
    assert reader.get(pdf).json() == {'kind': 'pdf', 'pages': 2}
    page = reader.get(pdf+'/page/2')
    assert page.status_code==200 and page.headers['content-type']=='image/png'
    assert reader.get(pdf+'/page/3').status_code==404


def test_consolidation_appends_to_original_office_files_and_reuses_drafts(setup, monkeypatch):
    clients, _ = setup
    client, owner = clients['admin']
    with SessionLocal() as db:
        bases = {base.name: base for base in db.scalars(select(KnowledgeBase))}
        base = bases[knowledge_consolidation.TARGET_BASE]
        platform = bases['平台基础资料库']
        clarification = bases['需求澄清知识库']
        base_id = base.id
        map_original = asset(db, base_id, owner, '授信执行能力地图', 'map.xlsx', workbook_bytes())
        paper_original = asset(db, base_id, owner, '授信产品白皮书', 'guide.docx', word_bytes(), published=True)
        published_id = asset(db, platform.id, owner, '执行规则', 'rules.txt', '新授信须核验额度'.encode(), published=True)
        asset(db, clarification.id, owner, '澄清待审核', 'draft.txt', '不应提供给模型'.encode())
        db.commit()

    calls = []
    evidence = ['S999']

    def complete(db, actor, messages, **options):
        payload = json.loads(messages[-1]['content'])
        assert len(payload['来源资料']) == 1
        assert payload['来源资料'][0]['evidence'][0]['text'] == '新授信须核验额度'
        calls.append(payload)
        return json.dumps({'changes': [{'capability': '=授信校验', 'map_update': '核验额度',
                  'whitepaper_update':'说明授信额度核验条件', 'assessment':'资料已说明', 'evidence': evidence}]}), {'model':'test'}

    monkeypatch.setattr(knowledge_consolidation, 'complete', complete)
    endpoint = f'/knowledge-bases/{base_id}/consolidation'
    assert clients['member'][0].get(endpoint).status_code == 403
    assert [group['ready_count'] for group in client.get(endpoint).json()['sources']] == [0, 1]
    assert client.post(endpoint).status_code == 502
    evidence[:] = ['S1']
    generated = client.post(endpoint)
    assert generated.status_code == 200, generated.text
    map_edit, paper_edit = [item['version_id'] for item in generated.json()['drafts']]
    assert client.post(endpoint).json() == {'drafts': generated.json()['drafts'], 'reused': True}
    assert len(calls) == 2

    with SessionLocal() as db:
        workbook_version = db.get(DocumentVersion, map_edit)
        assert workbook_version.parent_id == map_original
        assert workbook_version.provenance['sources'][0]['document_version_id'] == published_id
        with blob(workbook_version.file_hash).open('rb') as stream:
            workbook = load_workbook(stream)
            assert workbook.sheetnames == ['能力地图', '依赖规则', '知识沉淀']
            assert workbook.active['A2'].data_type == 's'
            assert workbook.active['B2'].value == '核验额度'
        paper_version = db.get(DocumentVersion, paper_edit)
        assert paper_version.parent_id == paper_original and paper_version.status == 'draft'
        assert db.get(Document, paper_version.document_id).current_version_id == paper_original
        word = WordDocument(blob(paper_version.file_hash))
        assert len(word.inline_shapes) == 1
        assert '说明授信额度核验条件' in [p.text for p in word.paragraphs]
