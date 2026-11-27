from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Document, DocumentVersion, ReviewRequest, ReviewTask, IndexBuild, Chunk, ModelConfig, Audit, Notification, User
from ..security import digest, write_lock
from ..config import settings
from .files import isolated_parse
from .ai import EmbeddingServiceError, embeddings


def parse_version(db: Session,version_id: str):
    version=db.get(DocumentVersion,version_id)
    if version.parse_status=='ready':
        return
    data=isolated_parse(version.file_hash,version.filename)
    version.content=data['content']
    version.blocks=data['blocks']
    version.warnings=data['warnings']
    version.content_hash=digest(version.content)
    version.parse_status='ready'
    db.commit()


def chunks_for(version: DocumentVersion) -> list[tuple[str,str]]:
    result=[]
    for block in version.blocks:
        text=block['text']
        for start in range(0,len(text),700):
            excerpt=text[start:start+800]
            if excerpt.strip():
                result.append((block['locator']+(f' / 字符{start}' if start else ''),excerpt))
    return result


def build_and_publish(db: Session,version_id: str,reindex: bool=False):
    version=db.get(DocumentVersion,version_id)
    if not reindex and version.publish_status=='published':
        return
    request=db.scalar(select(ReviewRequest).where(ReviewRequest.version_id==version.id))
    tasks=db.scalars(select(ReviewTask).where(ReviewTask.request_id==request.id)).all() if request else []
    if not request or request.status!='approved' or not tasks or any(t.decision!='approved' for t in tasks) or digest(version.content)!=request.locked_hash:
        raise RuntimeError('发布条件或锁定哈希不满足')
    config=db.scalar(select(ModelConfig).where(ModelConfig.kind=='embedding',ModelConfig.enabled.is_(True)).order_by(ModelConfig.created_at.desc()))
    build=IndexBuild(version_id=version.id,embedding_model=config.model if config else 'text-only',model_config_id=config.id if config else None,creator_id=version.creator_id)
    db.add(build)
    version.index_status='building'
    db.commit()
    try:
        candidates=chunks_for(version)
        if not candidates:
            raise RuntimeError('没有可索引片段')
        vectors=[]
        if config:
            try:
                for offset in range(0,len(candidates),32):
                    batch=embeddings(config,[t for _,t in candidates[offset:offset+32]])
                    if any(len(vector)!=settings.embedding_dimensions for vector in batch):
                        raise EmbeddingServiceError('Embedding 维度与配置不匹配')
                    vectors.extend(batch)
            except EmbeddingServiceError as error:
                vectors.clear()
                build.embedding_model='text-only'
                build.model_config_id=None
                db.add(Audit(actor_id=None,action='index.embedding_fallback',resource_id=version.id,detail={
                    'index_build_id':build.id,'embedding_model':config.model,'reason':str(error),
                }))
        for i,(locator,text) in enumerate(candidates):
            db.add(Chunk(build_id=build.id,version_id=version.id,ordinal=i,locator=locator,text=text,embedding=vectors[i] if vectors else None))
        build.chunks=len(candidates)
        build.status='ready'
        db.commit()
        write_lock(db)
        doc=db.scalar(select(Document).where(Document.id==version.document_id).with_for_update())
        db.refresh(version)
        # A slower job for an older approved revision cannot supersede a newer publication.
        current=db.get(DocumentVersion,doc.current_version_id) if doc.current_version_id else None
        if current and current.id!=version.id and current.created_at>version.created_at:
            version.status='superseded'
            version.publish_status='published'
            version.index_status='ready'
        elif not reindex or doc.current_version_id==version.id:
            if current and current.id!=version.id:
                current.status='superseded'
            doc.current_version_id=version.id
            doc.current_index_id=build.id
            version.status='published'
            version.publish_status='published'
            version.index_status='ready'
            db.add(Audit(actor_id=None,action='version.publish',resource_id=version.id,detail={'old_version_id':current.id if current else None,'index_build_id':build.id}))
            db.add(Notification(user_id=version.creator_id,message=f'已发布：{doc.title} {version.label}',resource_id=version.id))
        else:
            version.index_status='ready'
        db.commit()
    except Exception as error:
        db.rollback()
        build=db.get(IndexBuild,build.id)
        build.status='failed'
        build.error=str(error)[:2000]
        version=db.get(DocumentVersion,version_id)
        version.index_status='failed'
        if version.publish_status!='published':
            version.publish_status='failed'
        db.commit()
        raise
