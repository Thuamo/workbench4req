import json

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Requirement
from ..security import require_version
from .deletion import ensure_active
from .processing_tasks import readable_requirements


STATES = {'draft': '草稿', 'clarifying': '澄清中', 'confirmed': '已确认', 'specified': '已编制软需', 'published': '已发布'}


def selected_requirements(db, user, ids):
    if not ids:
        return []
    rows = {row.id: row for row in db.scalars(select(Requirement).where(Requirement.id.in_(ids), readable_requirements(user)))}
    if len(rows) != len(ids):
        raise HTTPException(404, '所选业务需求不存在或未授权')
    return [rows[requirement_id] for requirement_id in ids]


def collect_selected(db, user, requirements_ids, revisions, source_version_ids):
    requirements = selected_requirements(db, user, requirements_ids)
    versions = [require_version(db, vid, user) for vid in source_version_ids]
    if not requirements and not versions:
        raise RuntimeError('请选择至少一个业务需求或一份已解析文件')
    budget = min(14000, 80000 // (len(requirements) + len(versions)))
    excerpts = []
    for i, req in enumerate(requirements, 1):
        if req.revision != revisions.get(req.id):
            raise RuntimeError('所选需求已出现新修订，请重新选择资料并提交任务')
        text = json.dumps({'状态': STATES.get(req.state, req.state), '标签': req.tags,
                           '需求描述': req.description, '验收标准': req.acceptance}, ensure_ascii=False)
        excerpts.append({'key': f'R{i}', 'title': f'{req.number} {req.title}', 'revision': f'修订 {req.revision}',
                         'truncated': len(text) > budget, 'text': text[:budget]})
    for i, version in enumerate(versions, 1):
        ensure_active(db, 'document', version.document_id)
        if version.parse_status != 'ready':
            raise RuntimeError('所选文件尚未解析完成')
        text = '\n'.join(f"[{block.get('locator', '')}] {block.get('text', '')}" for block in version.blocks) or version.content
        excerpts.append({'key': f'D{i}', 'title': version.filename, 'revision': version.label,
                         'truncated': len(text) > budget, 'text': text[:budget]})
    return excerpts
