import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, Float, JSON, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .db import Base
from .config import settings


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(default=now)


DEVELOPMENT_MEMBER = 'development_member'
USER_ROLES = ('requirement_member', 'qa_member', 'reviewer', 'super_admin', DEVELOPMENT_MEMBER)


class User(Entity, Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint(f'role IN {USER_ROLES}', name='ck_users_role'),)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default='requirement_member')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Entity, Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]


class LoginAttempt(Entity, Base):
    __tablename__ = 'login_attempts'
    key: Mapped[str] = mapped_column(String(64), index=True)


class KnowledgeBase(Entity, Base):
    __tablename__ = 'knowledge_bases'
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default='')
    public: Mapped[bool] = mapped_column(Boolean, default=True)
    member_ids: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Folder(Entity, Base):
    __tablename__ = 'knowledge_folders'
    base_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_folders.id'))
    name: Mapped[str] = mapped_column(String(200))


class Document(Entity, Base):
    __tablename__ = 'knowledge_documents'
    title: Mapped[str] = mapped_column(String(300))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    base_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_folders.id'))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'))
    kind: Mapped[str] = mapped_column(String(30), default='reference')
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    current_index_id: Mapped[str | None] = mapped_column(String(36))


class DocumentVersion(Entity, Base):
    __tablename__ = 'document_versions'
    __table_args__ = (UniqueConstraint('document_id', 'label'), CheckConstraint("status IN ('draft','pending_review','in_review','approved','published','superseded','deprecated','archived')"))
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id'), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    label: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('document_versions.id'))
    filename: Mapped[str] = mapped_column(String(300))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default='')
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    parse_status: Mapped[str] = mapped_column(String(30), default='pending')
    review_status: Mapped[str] = mapped_column(String(30), default='not_submitted')
    publish_status: Mapped[str] = mapped_column(String(30), default='not_published')
    index_status: Mapped[str] = mapped_column(String(30), default='not_built')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    change_note: Mapped[str] = mapped_column(Text, default='')
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewRequest(Entity, Base):
    __tablename__ = 'review_requests'
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), unique=True)
    submitter_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    locked_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default='')


class ReviewTask(Entity, Base):
    __tablename__ = 'review_tasks'
    __table_args__ = (UniqueConstraint('request_id', 'reviewer_id'),)
    request_id: Mapped[str] = mapped_column(ForeignKey('review_requests.id'), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    decision: Mapped[str] = mapped_column(String(20), default='pending')
    comment: Mapped[str] = mapped_column(Text, default='')
    decided_at: Mapped[datetime | None]


class Outbox(Entity, Base):
    __tablename__ = 'outbox'
    __table_args__ = (UniqueConstraint('kind', 'resource_id'),)
    kind: Mapped[str] = mapped_column(String(30))
    resource_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None]
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str] = mapped_column(Text, default='')


class IndexBuild(Entity, Base):
    __tablename__ = 'index_builds'
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), index=True)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(20), default='building')
    embedding_model: Mapped[str] = mapped_column(String(200), default='text-only')
    model_config_id: Mapped[str | None] = mapped_column(ForeignKey('model_configs.id'))
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default='')


class Chunk(Entity, Base):
    __tablename__ = 'document_chunks'
    __table_args__ = (UniqueConstraint('build_id', 'ordinal'),)
    build_id: Mapped[str] = mapped_column(ForeignKey('index_builds.id'), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON().with_variant(Vector(settings.embedding_dimensions), 'postgresql'))


class Snapshot(Entity, Base):
    __tablename__ = 'knowledge_base_snapshots'
    __table_args__ = (UniqueConstraint('base_id', 'name'),)
    base_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'))
    creator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text, default='')
    manifest: Mapped[dict] = mapped_column(JSON)


class KnowledgeItem(Entity, Base):
    __tablename__ = 'knowledge_items'
    base_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'))
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40))
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)


class KnowledgeRevision(Entity, Base):
    __tablename__ = 'knowledge_item_versions'
    item_id: Mapped[str] = mapped_column(ForeignKey('knowledge_items.id'), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    source_version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'))
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class Requirement(Entity, Base):
    __tablename__ = 'requirements'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    number: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default='')
    state: Mapped[str] = mapped_column(String(30), default='draft')
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    acceptance: Mapped[str] = mapped_column(Text, default='')
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey('document_versions.id', use_alter=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Relation(Entity, Base):
    __tablename__ = 'requirement_relations'
    source_id: Mapped[str] = mapped_column(ForeignKey('requirements.id'))
    target_id: Mapped[str] = mapped_column(ForeignKey('requirements.id'))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default='candidate')
    evidence: Mapped[dict] = mapped_column(JSON)


class RequirementContext(Entity, Base):
    __tablename__ = 'requirement_contexts'
    requirement_id: Mapped[str] = mapped_column(ForeignKey('requirements.id'), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default='business')
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'), index=True)
    origin_run_id: Mapped[str | None] = mapped_column(ForeignKey('agent_runs.id'))


class Metric(Entity, Base):
    __tablename__ = 'requirement_metrics'
    requirement_id: Mapped[str] = mapped_column(ForeignKey('requirements.id'))
    method_version: Mapped[str] = mapped_column(String(50))
    values: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[dict] = mapped_column(JSON)


class ClarificationTask(Entity, Base):
    __tablename__ = 'clarification_tasks'
    __table_args__ = (UniqueConstraint('owner_id', 'import_key'),)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'))
    import_key: Mapped[str | None] = mapped_column(String(150))
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    revision: Mapped[int] = mapped_column(Integer, default=1)


class TaskHistory(Entity, Base):
    __tablename__ = 'clarification_task_history'
    task_id: Mapped[str] = mapped_column(ForeignKey('clarification_tasks.id'))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    fields: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)


class Question(Entity, Base):
    __tablename__ = 'clarification_questions'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    task_id: Mapped[str | None] = mapped_column(ForeignKey('clarification_tasks.id'))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default='')
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[str] = mapped_column(String(100), default='')
    feedback: Mapped[str] = mapped_column(Text, default='')
    conclusion: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='open')


class Skill(Entity, Base):
    __tablename__ = 'skills'
    owner_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(100))
    command: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    publication_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    publication_version_id: Mapped[str | None] = mapped_column(String(36))
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class SkillVersion(Entity, Base):
    __tablename__ = 'skill_versions'
    skill_id: Mapped[str] = mapped_column(ForeignKey('skills.id'), index=True)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    config: Mapped[dict] = mapped_column(JSON)


class Conversation(Entity, Base):
    __tablename__ = 'conversations'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(150), default='新聊天')
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Message(Entity, Base):
    __tablename__ = 'messages'
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id'), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    generation_status: Mapped[str] = mapped_column(String(20), default='completed')
    citations: Mapped[list] = mapped_column(JSON, default=list)
    version_ids: Mapped[list] = mapped_column(JSON, default=list)
    model_config_id: Mapped[str | None] = mapped_column(ForeignKey('model_configs.id'))


class AgentRun(Entity, Base):
    __tablename__ = 'agent_runs'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    skill_version_id: Mapped[str] = mapped_column(ForeignKey('skill_versions.id'))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey('conversations.id'))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    inputs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    model_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')


class AgentStep(Entity, Base):
    __tablename__ = 'agent_steps'
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id'), index=True)
    agent: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(Text)
    output: Mapped[dict] = mapped_column(JSON)


class ModelConfig(Entity, Base):
    __tablename__ = 'model_configs'
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default='chat')
    encrypted_key: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Audit(Entity, Base):
    __tablename__ = 'audit_logs'
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(Entity, Base):
    __tablename__ = 'notifications'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    message: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[str] = mapped_column(String(36))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Entity, Base):
    __tablename__ = 'system_settings'
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict] = mapped_column(JSON)


class DeletedRecord(Entity, Base):
    __tablename__ = 'deleted_records'
    __table_args__ = (UniqueConstraint('resource_type','resource_id'),)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(36))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    deleted_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    reason: Mapped[str] = mapped_column(Text, default='用户删除')


class DocumentWorkspace(Entity, Base):
    __tablename__ = 'document_workspaces'
    __table_args__ = (UniqueConstraint('owner_id','origin_key'),)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    origin_key: Mapped[str] = mapped_column(String(90))
    run_id: Mapped[str | None] = mapped_column(ForeignKey('agent_runs.id'))
    document_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_documents.id'))
    version_id: Mapped[str | None] = mapped_column(ForeignKey('document_versions.id'))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'))
    title: Mapped[str] = mapped_column(String(300))
    label: Mapped[str] = mapped_column(String(80), default='V1.0')
    base_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_bases.id'))
    folder_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_folders.id'))
    content_json: Mapped[dict | None] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text, default='')
    change_note: Mapped[str] = mapped_column(Text, default='')
    sources: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_revision: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(default=now)


class DocumentAssistantMessage(Entity, Base):
    __tablename__ = 'document_assistant_messages'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('document_workspaces.id'), index=True)
    role: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class DocumentComment(Entity, Base):
    __tablename__ = 'document_comments'
    __table_args__ = (CheckConstraint('(workspace_id IS NULL) <> (version_id IS NULL)', name='ck_document_comment_scope'),)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey('document_workspaces.id'), index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey('document_versions.id'), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    quote: Mapped[str] = mapped_column(Text, default='')
    anchor: Mapped[dict | None] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text)


class DocumentImage(Entity, Base):
    __tablename__ = 'document_images'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('document_workspaces.id'), index=True)
    file_hash: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(30))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)


class DocumentProposal(Entity, Base):
    __tablename__ = 'document_proposals'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('document_workspaces.id'), index=True)
    base_revision: Mapped[int] = mapped_column(Integer)
    before_content: Mapped[str] = mapped_column(Text)
    suggested_content: Mapped[str] = mapped_column(Text)
    preview_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class DocumentChange(Entity, Base):
    __tablename__ = 'document_changes'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('document_workspaces.id'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey('document_proposals.id'), unique=True)
    revision: Mapped[int] = mapped_column(Integer)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict] = mapped_column(JSON)
    before_content: Mapped[str] = mapped_column(Text)
    after_content: Mapped[str] = mapped_column(Text)


class ProcessingTaskContext(Entity, Base):
    __tablename__ = 'processing_task_contexts'
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id'), unique=True)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'), index=True)
    legacy_requirement_id: Mapped[str | None] = mapped_column(ForeignKey('requirements.id'))
    legacy_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class TaskDocument(Entity, Base):
    __tablename__ = 'processing_task_documents'
    __table_args__ = (UniqueConstraint('run_id','version_id','role'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id'), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'))
    role: Mapped[str] = mapped_column(String(20))


class RequirementPack(Entity, Base):
    __tablename__ = 'requirement_packs'
    __table_args__ = (UniqueConstraint('requirement_id','number'),)
    requirement_id: Mapped[str] = mapped_column(ForeignKey('requirements.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))


class RequirementPackDocument(Entity, Base):
    __tablename__ = 'requirement_pack_documents'
    __table_args__ = (UniqueConstraint('pack_id','stage','version_id'),)
    pack_id: Mapped[str] = mapped_column(ForeignKey('requirement_packs.id'), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'))


class RequirementPackSpecification(Entity, Base):
    __tablename__ = 'requirement_pack_specifications'
    pack_id: Mapped[str] = mapped_column(ForeignKey('requirement_packs.id'), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id'), unique=True)
