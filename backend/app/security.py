import hashlib, secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from .db import get_db
from .models import DEVELOPMENT_MEMBER, User, AuthSession, LoginAttempt, KnowledgeBase, Document, DocumentVersion, ReviewRequest, ReviewTask, Audit, now
from .config import settings
from fastapi.encoders import jsonable_encoder

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(24))

DEVELOPMENT_READ_ROUTES = {
    '/auth/me', '/notifications',
    '/knowledge-bases', '/knowledge-bases/{base_id}/folders', '/search',
    '/documents', '/documents/{document_id}', '/documents/{document_id}/versions',
    '/documents/{document_id}/versions/{version_id}', '/documents/{document_id}/diff',
    '/versions/{version_id}/download', '/versions/{version_id}/export',
    '/versions/{version_id}/source-preview', '/versions/{version_id}/source-preview/image/{index}',
    '/versions/{version_id}/source-preview/page/{page}',
    '/versions/{id}/comments', '/document-images/{id}',
    '/requirements', '/requirements/{requirement_id}/workspace', '/relations',
    '/processing-tasks', '/processing-tasks/{id}',
    '/conversations', '/conversations/{conversation_id}/messages',
}
DEVELOPMENT_OTHER_ROUTES = {
    ('POST', '/auth/logout'), ('POST', '/auth/password'), ('POST', '/notifications/{notification_id}/read'),
    ('POST', '/conversations'), ('POST', '/conversations/{conversation_id}/messages'),
    ('PATCH', '/conversations/{conversation_id}'), ('DELETE', '/conversations/{conversation_id}'),
    ('POST', '/versions/{version_id}/export-preview'),
}


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def verify(password: str, encoded: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get('session', '')
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token), AuthSession.expires_at > now()))
    user = db.get(User, session.user_id) if session else None
    if not user or not user.enabled:
        raise HTTPException(401, '登录已失效')
    if user.role == DEVELOPMENT_MEMBER:
        path = getattr(request.scope.get('route'), 'path', None)
        if not (request.method in ('GET', 'HEAD') and path in DEVELOPMENT_READ_ROUTES
                or (request.method, path) in DEVELOPMENT_OTHER_ROUTES):
            raise HTTPException(403, '开发组成员仅可查看需求与知识库，并使用知识问答')
    return user


def admin(user: User = Depends(current_user)) -> User:
    if user.role != 'super_admin':
        raise HTTPException(403, '需要管理员权限')
    return user


def reviewer(user: User = Depends(current_user)) -> User:
    if user.role not in ('reviewer', 'super_admin'):
        raise HTTPException(403, '需要审核权限')
    return user


def base_allowed(base: KnowledgeBase, user: User) -> bool:
    return base.enabled and (base.public or user.role == 'super_admin' or user.id in base.member_ids)


def require_base(db: Session, base_id: str, user: User) -> KnowledgeBase:
    base = db.get(KnowledgeBase, base_id)
    if not base or not base_allowed(base, user):
        raise HTTPException(404, '知识库不存在或未授权')
    return base


def owned(obj, user: User):
    if not obj or obj.owner_id != user.id:
        raise HTTPException(404, '资源不存在或未授权')
    return obj


def can_version(db: Session, version: DocumentVersion, user: User) -> bool:
    doc = db.get(Document, version.document_id)
    if user.role == 'super_admin' or version.creator_id == user.id:
        return True
    if version.publish_status=='published' and version.status in ('published', 'superseded','deprecated','archived') and base_allowed(db.get(KnowledgeBase, doc.base_id), user):
        return True
    return bool(db.scalar(select(ReviewTask.id).join(ReviewRequest, ReviewRequest.id == ReviewTask.request_id).where(ReviewRequest.version_id == version.id, ReviewTask.reviewer_id == user.id)))


def require_version(db: Session, version_id: str, user: User) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if not version or not can_version(db, version, user):
        raise HTTPException(404, '版本不存在或未授权')
    return version


def audit(db: Session, user: User | None, action: str, resource_id: str, **detail):
    db.add(Audit(actor_id=user.id if user else None, action=action, resource_id=resource_id, detail=jsonable_encoder(detail)))


def cipher() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise HTTPException(503, '请先配置 ENCRYPTION_KEY，再保存模型密钥')
    return Fernet(key.encode())


def rate_limit(db: Session, key: str):
    count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == key, LoginAttempt.created_at > now()-timedelta(minutes=15)))
    if count >= 10:
        raise HTTPException(429, '尝试过于频繁，请15分钟后重试')


def write_lock(db: Session):
    # SQLite has no SELECT FOR UPDATE. Serialize writes before reading guarded state.
    if db.in_transaction():
        db.rollback()
    if db.bind.dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
