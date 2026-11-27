import difflib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import KnowledgeBase, Folder, Document, DocumentVersion, User, Snapshot, KnowledgeItem, KnowledgeRevision, ModelConfig
from ..security import current_user, admin, require_base, base_allowed, require_version, audit
from ..schemas import BaseInput, FolderInput, SnapshotInput, KnowledgeInput
from ..serialize import record
from ..services.search import search
from ..services.knowledge_consolidation import consolidate, inspect as inspect_consolidation

from ..services.deletion import active_filter, ensure_active

router=APIRouter(tags=['知识库'])


@router.get('/knowledge-bases')
def bases(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return [record(b) for b in db.scalars(select(KnowledgeBase)).all() if base_allowed(b,user)]


@router.post('/knowledge-bases')
def create_base(data: BaseInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    base=KnowledgeBase(**data.model_dump())
    db.add(base)
    db.flush()
    audit(db,user,'base.create',base.id)
    db.commit()
    return record(base)


@router.patch('/knowledge-bases/{base_id}')
def edit_base(base_id: str,data: BaseInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    base=db.get(KnowledgeBase,base_id)
    if not base:
        raise HTTPException(404,'知识库不存在')
    for k,v in data.model_dump().items():
        setattr(base,k,v)
    audit(db,user,'base.edit',base.id,settings=data.model_dump())
    db.commit()
    return record(base)


@router.delete('/knowledge-bases/{base_id}')
def delete_base(base_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    base=db.get(KnowledgeBase,base_id)
    if not base:
        raise HTTPException(404,'知识库不存在')
    # Retain version and snapshot references; deletion is a governed tombstone.
    base.enabled=False
    audit(db,user,'base.disable',base.id)
    db.commit()
    return {'ok':True}


@router.get('/knowledge-bases/{base_id}/folders')
def folders(base_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    return [record(f) for f in db.scalars(select(Folder).where(Folder.base_id==base_id)).all()]


@router.get('/knowledge-bases/{base_id}/consolidation')
def consolidation_setup(base_id: str, user: User=Depends(admin), db: Session=Depends(get_db)):
    return inspect_consolidation(db, base_id, user).describe()


@router.post('/knowledge-bases/{base_id}/consolidation')
def run_consolidation(base_id: str, user: User=Depends(admin), db: Session=Depends(get_db)):
    return consolidate(db, base_id, user)


@router.post('/knowledge-bases/{base_id}/folders')
def create_folder(base_id: str,data: FolderInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    if data.parent_id:
        parent=db.get(Folder,data.parent_id)
        if not parent or parent.base_id!=base_id:
            raise HTTPException(422,'父目录不属于知识库')
    folder=Folder(base_id=base_id,**data.model_dump())
    db.add(folder)
    db.flush()
    audit(db,user,'folder.create',folder.id)
    db.commit()
    return record(folder)


@router.patch('/folders/{folder_id}')
def rename_folder(folder_id: str,data: FolderInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    folder=db.get(Folder,folder_id)
    if not folder:
        raise HTTPException(404,'目录不存在')
    if data.parent_id:
        parent=db.get(Folder,data.parent_id)
        seen={folder.id}
        while parent:
            if parent.id in seen or parent.base_id!=folder.base_id:
                raise HTTPException(422,'目录循环或跨知识库')
            seen.add(parent.id)
            parent=db.get(Folder,parent.parent_id) if parent.parent_id else None
    folder.name=data.name
    folder.parent_id=data.parent_id
    db.commit()
    return record(folder)


@router.delete('/folders/{folder_id}')
def delete_folder(folder_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    folder=db.get(Folder,folder_id)
    if not folder:
        raise HTTPException(404,'目录不存在')
    if db.scalar(select(Folder.id).where(Folder.parent_id==folder_id)) or db.scalar(select(Document.id).where(Document.folder_id==folder_id)):
        raise HTTPException(409,'请先移动目录内的资产和子目录')
    db.delete(folder)
    audit(db,user,'folder.delete',folder_id)
    db.commit()
    return {'ok':True}


@router.get('/search')
def retrieve(q: str,base_id: str | None=None,snapshot_id: str | None=None,version_id: str | None=None,as_of: datetime | None=None,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if len(q)>2000:
        raise HTTPException(422,'查询过长')
    return search(db,user,q,[base_id] if base_id else None,snapshot_id,version_id,as_of=as_of)


@router.get('/knowledge-bases/{base_id}/snapshots')
def snapshots(base_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    return [record(s) for s in db.scalars(select(Snapshot).where(Snapshot.base_id==base_id).order_by(Snapshot.created_at.desc())).all()]


@router.post('/knowledge-bases/{base_id}/snapshots')
def create_snapshot(base_id: str,data: SnapshotInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    documents=db.scalars(select(Document).where(Document.base_id==base_id,Document.current_version_id.is_not(None))).all()
    items=db.scalars(select(KnowledgeItem).where(KnowledgeItem.base_id==base_id,KnowledgeItem.deprecated.is_(False),KnowledgeItem.current_revision_id.is_not(None))).all()
    manifest={'documents':[{'document_id':d.id,'version_id':d.current_version_id,'index_id':d.current_index_id} for d in documents],'knowledge':[{'item_id':i.id,'revision_id':i.current_revision_id} for i in items],'models':[record(m,('encrypted_key',)) for m in db.scalars(select(ModelConfig).where(ModelConfig.enabled.is_(True))).all()]}
    snapshot=Snapshot(base_id=base_id,creator_id=user.id,name=data.name,note=data.note,manifest=manifest)
    db.add(snapshot)
    db.flush()
    audit(db,user,'snapshot.create',snapshot.id)
    db.commit()
    return record(snapshot)


@router.get('/knowledge-bases/{base_id}/snapshots/{snapshot_id}')
def snapshot_detail(base_id: str,snapshot_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    snapshot=db.get(Snapshot,snapshot_id)
    if not snapshot or snapshot.base_id!=base_id:
        raise HTTPException(404,'快照不存在')
    return record(snapshot)


def manifest_diff(left: dict,right: dict) -> dict:
    result={}
    for key,identity,version in [('documents','document_id','version_id'),('knowledge','item_id','revision_id')]:
        a={i[identity]:i[version] for i in left[key]}
        b={i[identity]:i[version] for i in right[key]}
        result[key]={'added':{k:v for k,v in b.items() if k not in a},'removed':{k:v for k,v in a.items() if k not in b},'updated':{k:{'left':a[k],'right':v} for k,v in b.items() if k in a and a[k]!=v}}
    return result


@router.get('/knowledge-bases/{base_id}/snapshot-diff')
def snapshot_diff(base_id: str,left: str,right: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    a=snapshot_detail(base_id,left,user,db)
    b=snapshot_detail(base_id,right,user,db)
    return manifest_diff(a['manifest'],b['manifest'])


@router.post('/knowledge-bases/{base_id}/restore-proposal')
def restore_proposal(base_id: str,data: dict,user: User=Depends(admin),db: Session=Depends(get_db)):
    snapshot=snapshot_detail(base_id,str(data.get('snapshot_id','')),user,db)
    current={'documents':[{'document_id':d.id,'version_id':d.current_version_id} for d in db.scalars(select(Document).where(Document.base_id==base_id,Document.current_version_id.is_not(None))).all()],'knowledge':[{'item_id':i.id,'revision_id':i.current_revision_id} for i in db.scalars(select(KnowledgeItem).where(KnowledgeItem.base_id==base_id,KnowledgeItem.deprecated.is_(False))).all()]}
    changes=manifest_diff(current,snapshot['manifest'])
    audit(db,user,'snapshot.restore_proposal',snapshot['id'],changes=changes)
    db.commit()
    return {'changes':changes,'requires_review':True,'message':'为需恢复的文档创建新修订并重新会签；此提案未切换正式版本'}


@router.get('/knowledge-items')
def items(base_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    return [record(i) for i in db.scalars(select(KnowledgeItem).where(KnowledgeItem.base_id==base_id,active_filter('knowledge_item',KnowledgeItem.id))).all()]


def revision_item(db: Session,item: KnowledgeItem,data: KnowledgeInput,user: User):
    ensure_active(db,'knowledge_item',item.id)
    version=require_version(db,data.source_version_id,user)
    doc=db.get(Document,version.document_id)
    if doc.base_id!=item.base_id or version.status not in ('published','superseded'):
        raise HTTPException(422,'知识版本必须引用本知识库已发布的来源')
    if not any(b['locator']==data.locator for b in version.blocks):
        raise HTTPException(422,'来源定位不属于该版本')
    revision=KnowledgeRevision(item_id=item.id,creator_id=user.id,source_version_id=version.id,content=data.content,locator=data.locator,reason=data.reason,confirmed=True)
    db.add(revision)
    db.flush()
    item.current_revision_id=revision.id
    audit(db,user,'knowledge.confirm_revision',revision.id,source_version_id=version.id,reason=data.reason)
    return revision


@router.post('/knowledge-bases/{base_id}/items')
def create_item(base_id: str,data: KnowledgeInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    require_base(db,base_id,user)
    item=KnowledgeItem(base_id=base_id,name=data.name,kind=data.kind)
    db.add(item)
    db.flush()
    revision_item(db,item,data,user)
    db.commit()
    return record(item)


@router.get('/knowledge-items/{item_id}/versions')
def item_versions(item_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    item=db.get(KnowledgeItem,item_id)
    if not item:
        raise HTTPException(404,'条目不存在')
    require_base(db,item.base_id,user)
    return [record(v) for v in db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.item_id==item_id)).all()]


@router.post('/knowledge-items/{item_id}/revisions')
def item_revision(item_id: str,data: KnowledgeInput,user: User=Depends(admin),db: Session=Depends(get_db)):
    item=db.get(KnowledgeItem,item_id)
    if not item:
        raise HTTPException(404,'条目不存在')
    revision=revision_item(db,item,data,user)
    db.commit()
    return record(revision)


@router.get('/knowledge-items/{item_id}/diff')
def item_diff(item_id: str,left: str,right: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    versions=item_versions(item_id,user,db)
    mapping={v['id']:v for v in versions}
    if left not in mapping or right not in mapping:
        raise HTTPException(404,'版本不存在')
    return {'diff':list(difflib.unified_diff(mapping[left]['content'].splitlines(),mapping[right]['content'].splitlines(),fromfile=left,tofile=right))}


@router.post('/knowledge-items/{item_id}/deprecate')
def item_deprecate(item_id: str,user: User=Depends(admin),db: Session=Depends(get_db)):
    item=db.get(KnowledgeItem,item_id)
    if not item:
        raise HTTPException(404,'条目不存在')
    item.deprecated=True
    audit(db,user,'knowledge.deprecate',item.id)
    db.commit()
    return record(item)
