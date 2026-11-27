import io

import pymupdf
from docx import Document as Word

from test_editing_workflow import fixture_run


def test_specification_comments_and_images_follow_version_access(setup):
    member, base, run_id, _ = fixture_run(setup)
    clients, _ = setup
    reviewer, reviewer_id = clients['review_a']
    outsider = clients['other'][0]
    opened = member.post('/document-workspaces/open', json={'run_id': run_id}).json()
    path = f"/document-workspaces/{opened['id']}"
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60), False)
    image.clear_with(220)

    def upload(extension):
        return member.post(path + '/images', files={'file': ('流程图.'+extension, image.tobytes(extension))})

    photo = upload('png')
    assert photo.status_code == 200, photo.text
    unused = upload('jpeg').json()
    picture = photo.json()
    asset_path = picture['src'].removeprefix('/api')
    assert member.get(asset_path).headers['content-type'] == 'image/png'
    assert reviewer.get(asset_path).status_code == 404
    assert member.post(path + '/images', files={'file': ('伪装图片.png', b'<svg/>', 'image/png')}).status_code == 422
    assert outsider.post(path + '/images', files={'file': ('流程图.png', image.tobytes('png'))}).status_code == 404

    body = {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': '此处说明审批流程'}]},
        {'type': 'image', 'attrs': {**picture, 'textAlign': 'center'}},
    ]}
    fields = {'expected_revision': opened['revision'], 'base_id': base, 'title': '审批软需', 'label': 'V1.0'}
    unsafe = {'type': 'doc', 'content': [{'type': 'image', 'attrs': {'src':'https://example.invalid/picture.png'}}]}
    assert member.put(path, json={**fields, 'content_json': unsafe}).status_code == 422
    missing = {'type': 'doc', 'content': [{'type': 'image', 'attrs': {'src':'/api/document-images/11111111-1111-1111-1111-111111111111'}}]}
    assert member.put(path, json={**fields, 'content_json': missing}).status_code == 422
    invalid_alignment = {'type': 'doc', 'content': [{'type': 'image', 'attrs': {**picture, 'textAlign': 'justify'}}]}
    assert member.put(path, json={**fields, 'content_json': invalid_alignment}).status_code == 422
    saved = member.put(path, json={**fields, 'content_json': body})
    assert saved.status_code == 200, saved.text
    assert member.get(path).json()['content_json']==body
    anchor = {'offset':4,'before':'此处说明','after':''}
    note = {'quote': '审批流程', 'content': '补充审批分支', 'anchor': anchor}
    added = member.post(path + '/comments', json=note)
    assert added.status_code == 200, added.text
    assert reviewer.get(path + '/comments').status_code == 404
    assert reviewer.post(path + '/comments', json=note).status_code == 404

    confirmed = member.post(path + '/confirm', json={'expected_revision': saved.json()['revision']})
    assert confirmed.status_code == 200, confirmed.text
    version = confirmed.json()
    version_path = f"/versions/{version['id']}"
    comments = version_path + '/comments'
    assert picture['src'] in version['content']
    assert version['provenance']['rich_text'] == body
    shared = member.get(comments).json()[0]
    assert shared['id'] == added.json()['id'] and shared['anchor'] == anchor
    assert reviewer.post(comments, json=note).status_code == 404

    export = member.get(version_path + '/export')
    assert export.status_code == 200, export.text
    assert len(Word(io.BytesIO(export.content)).inline_shapes) == 1
    restored = member.post(f"/documents/{version['document_id']}/restore-draft", json={
        'source_version_id':version['id'], 'label':'V2.0',
    })
    assert restored.status_code == 200, restored.text
    assert restored.json()['provenance']['image_ids'] == version['provenance']['image_ids']

    submit = member.post(version_path + '/submit', json={'reviewer_ids': [reviewer_id, clients['review_b'][1]]})
    assert submit.status_code == 200, submit.text
    review_note = reviewer.post(comments, json={'content': '流程图可供核对', 'quote': '审批流程'})
    assert review_note.status_code == 200, review_note.text
    assert reviewer.get(asset_path).content == image.tobytes('png')
    assert reviewer.get(unused['src'].removeprefix('/api')).status_code == 404
    assert outsider.get(asset_path).status_code == 404
    assert outsider.get(comments).status_code == 404
    assert len(member.get(comments).json()) == 2
    assert member.delete(comments + '/' + review_note.json()['id']).status_code == 403
    assert reviewer.delete(comments + '/' + review_note.json()['id']).status_code == 200
    unchanged = member.get(f"/documents/{version['document_id']}/versions/{version['id']}").json()
    assert unchanged['content_hash'] == version['content_hash']
