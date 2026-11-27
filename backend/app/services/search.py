import math, re
from datetime import datetime, timezone
from types import SimpleNamespace
from collections import Counter
import jieba
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import Document, DocumentVersion, Chunk, IndexBuild, KnowledgeBase, Snapshot, ModelConfig, User, Audit, KnowledgeItem, KnowledgeRevision
from ..security import base_allowed, require_base
from .ai import embeddings


def tokens(text: str) -> list[str]:
    return [x.lower() for x in jieba.cut_for_search(text) if re.search(r'[\w\u4e00-\u9fff]',x)]


def search(db: Session,user: User,query: str,base_ids: list[str] | None=None,snapshot_id: str | None=None,version_id: str | None=None,limit: int=10,as_of: datetime | None=None) -> list[dict]:
    if sum(bool(value) for value in (snapshot_id,version_id,as_of))>1:
        raise HTTPException(422,'快照、版本和历史时间只能选择一个')
    if as_of and as_of.tzinfo:
        as_of=as_of.astimezone(timezone.utc).replace(tzinfo=None)
    bases=[b.id for b in db.scalars(select(KnowledgeBase)).all() if base_allowed(b,user) and (not base_ids or b.id in base_ids)]
    if base_ids:
        for bid in base_ids:
            require_base(db,bid,user)
    builds=[]
    if snapshot_id:
        snapshot=db.get(Snapshot,snapshot_id)
        if not snapshot:
            raise HTTPException(404,'快照不存在')
        require_base(db,snapshot.base_id,user)
        builds=[d['index_id'] for d in snapshot.manifest['documents'] if d['index_id']]
    elif version_id:
        version=db.get(DocumentVersion,version_id)
        if not version or version.status not in ('published','superseded'):
            raise HTTPException(404,'指定版本尚未发布')
        doc=db.get(Document,version.document_id)
        require_base(db,doc.base_id,user)
        build=db.scalar(select(IndexBuild).where(IndexBuild.version_id==version_id,IndexBuild.status=='ready').order_by(IndexBuild.created_at.desc()))
        builds=[build.id] if build else []
    elif as_of:
        allowed_documents={d.id:d for d in db.scalars(select(Document).where(Document.base_id.in_(bases))).all()}
        active={}
        events=db.scalars(select(Audit).where(Audit.action.in_(['version.publish','version.retire']),Audit.created_at<=as_of).order_by(Audit.created_at)).all()
        for event in events:
            version=db.get(DocumentVersion,event.resource_id)
            if not version or version.document_id not in allowed_documents:
                continue
            if event.action=='version.retire':
                if active.get(version.document_id,{}).get('version')==version.id:
                    active.pop(version.document_id,None)
            else:
                build=db.get(IndexBuild,event.detail.get('index_build_id'))
                if build and build.status=='ready':
                    active[version.document_id]={'version':version.id,'index':build.id}
        builds=[entry['index'] for entry in active.values()]
    else:
        builds=[d.current_index_id for d in db.scalars(select(Document).where(Document.base_id.in_(bases))).all() if d.current_index_id]
    entries=db.scalars(select(Chunk).where(Chunk.build_id.in_(builds))).all()
    knowledge={}
    items=db.scalars(select(KnowledgeItem).where(KnowledgeItem.base_id.in_(bases))).all()
    snapshot_revisions={entry['revision_id'] for entry in snapshot.manifest.get('knowledge',[])} if snapshot_id else None
    for item in items:
        if snapshot_revisions is not None:
            revisions=db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.item_id==item.id,KnowledgeRevision.id.in_(snapshot_revisions))).all()
        elif as_of:
            revision=db.scalar(select(KnowledgeRevision).where(KnowledgeRevision.item_id==item.id,KnowledgeRevision.created_at<=as_of,KnowledgeRevision.confirmed.is_(True)).order_by(KnowledgeRevision.created_at.desc()))
            revisions=[revision] if revision else []
        else:
            revision=db.get(KnowledgeRevision,item.current_revision_id) if item.current_revision_id and not item.deprecated else None
            revisions=[revision] if revision else []
        for revision in revisions:
            if not revision.confirmed or (version_id and revision.source_version_id!=version_id):
                continue
            source=db.get(DocumentVersion,revision.source_version_id)
            if not source or source.status not in ('published','superseded'):
                continue
            if as_of and not db.scalar(select(Audit.id).where(Audit.action=='version.publish',Audit.resource_id==source.id,Audit.created_at<=as_of)):
                continue
            knowledge[revision.id]=(item,revision)
            entries.append(SimpleNamespace(id=revision.id,text=item.name+'\n'+revision.content,locator=revision.locator,build_id=None,version_id=revision.source_version_id,embedding=None))
    if not entries:
        return []
    query_tokens=tokens(query)
    if not query_tokens:
        return []
    lengths=[len(tokens(c.text)) for c in entries]
    avg_length=sum(lengths)/max(1,len(entries))
    counts=[Counter(tokens(c.text)) for c in entries]
    df={t:sum(t in c for c in counts) for t in set(query_tokens)}
    lexical=[]
    for i,c in enumerate(entries):
        score=0.0
        for t in set(query_tokens):
            frequency=counts[i][t]
            idf=math.log(1+(len(entries)-df[t]+0.5)/(df[t]+0.5))
            score+=idf*frequency*2.2/(frequency+1.2*(0.25+0.75*lengths[i]/max(avg_length,1)))
        if query.lower() in c.text.lower():
            score+=5
        if score>0:
            lexical.append((c.id,score))
    ranked={cid:1/(60+rank) for rank,(cid,_) in enumerate(sorted(lexical,key=lambda x:-x[1]),1)}
    # Every embedding candidate already passed base/version ACL filtering.
    config=db.scalar(select(ModelConfig).where(ModelConfig.kind=='embedding',ModelConfig.enabled.is_(True)).order_by(ModelConfig.created_at.desc()))
    if config:
        selected=[c for c in entries if c.embedding is not None and db.get(IndexBuild,c.build_id).model_config_id==config.id]
        if selected:
            q=embeddings(config,[query])[0]
            similarity=[]
            for c in selected:
                vector=list(c.embedding)
                if len(q)!=len(vector):
                    raise RuntimeError('检索向量维度与索引不兼容，请重新索引')
                cosine=sum(a*b for a,b in zip(q,vector))/(math.sqrt(sum(a*a for a in q))*math.sqrt(sum(a*a for a in vector)) or 1)
                if cosine>0.15:
                    similarity.append((c.id,cosine))
            for rank,(cid,_) in enumerate(sorted(similarity,key=lambda x:-x[1]),1):
                ranked[cid]=ranked.get(cid,0)+1/(60+rank)
    by_id={c.id:c for c in entries}
    result=[]
    for cid,score in sorted(ranked.items(),key=lambda x:-x[1])[:limit]:
        c=by_id[cid]
        v=db.get(DocumentVersion,c.version_id)
        d=db.get(Document,v.document_id)
        if d.base_id not in bases:
            continue
        item,revision=knowledge.get(c.id,(None,None))
        result.append({'citation_id':c.id,'document_id':d.id,'document_version_id':v.id,'index_build_id':c.build_id,'knowledge_base_id':d.base_id,'knowledge_item_id':item.id if item else None,'knowledge_revision_id':revision.id if revision else None,'title':item.name if item else d.title,'version':v.label,'locator':c.locator,'excerpt':c.text,'current':d.current_version_id==v.id,'score':round(score,5)})
    return result
