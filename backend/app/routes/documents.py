import difflib
from pathlib import Path
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Document, DocumentVersion, User, Folder, KnowledgeBase, Outbox, IndexBuild, ReviewRequest, ReviewTask, Audit, Requirement, KnowledgeRevision, KnowledgeItem, AgentRun
from ..schemas import VersionInput, EditVersion, Submit, BatchSubmit, DocumentMetadata
from ..security import current_user, require_base, require_version, can_version, owned, audit, digest, write_lock
from ..serialize import record
from ..services.files import validate, store, blob, text_blocks
from ..services.source_preview import source_preview
from ..services.review import submit_review, batch_submit
from ..services.export import export_docx
from ..services.document_images import version_images
from ..services.richtext import image_ids
from ..config import settings

from ..services.deletion import active_filter, ensure_active, is_deleted

router=APIRouter(tags=['文档与版本'])


def document_location(db: Session,doc: Document):
    base=db.get(KnowledgeBase,doc.base_id)
    path=[]
    folder_id=doc.folder_id
    seen=set()
    while folder_id and folder_id not in seen:
        seen.add(folder_id)
        folder=db.get(Folder,folder_id)
        if not folder or folder.base_id!=doc.base_id: break
        path.insert(0,{'id':folder.id,'name':folder.name})
        folder_id=folder.parent_id
    return {'base_name':base.name if base else '知识库','folder_path':path,
            'location_path':' / '.join([base.name if base else '知识库',*[p['name'] for p in path]] if path else [base.name if base else '知识库','根目录'])}


def document_access(db: Session,document_id: str,user: User) -> Document:
    doc=db.get(Document,document_id)
    if not doc:
        raise HTTPException(404,'文档不存在')
    versions=db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document_id)).all()
    if not any(can_version(db,v,user) for v in versions):
        raise HTTPException(404,'文档未授权')
    return doc


@router.get('/documents')
def documents(base_id: str | None=None,user: User=Depends(current_user),db: Session=Depends(get_db)):
    result=[]
    for doc in db.scalars(select(Document).where(active_filter('document',Document.id)).order_by(Document.created_at.desc())).all():
        if base_id and doc.base_id!=base_id:
            continue
        versions=[v for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id).order_by(DocumentVersion.created_at.desc())).all() if can_version(db,v,user)]
        if versions:
            result.append({**record(doc),**document_location(db,doc),'versions':[record(v,('content','blocks')) for v in versions]})
    return result


@router.get('/documents/{document_id}')
def metadata(document_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    doc=document_access(db,document_id,user)
    return {**record(doc),**document_location(db,doc),'deleted':is_deleted(db,'document',document_id)}


@router.patch('/documents/{document_id}')
def edit_metadata(document_id: str,data: DocumentMetadata,user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..models import RequirementPackSpecification
    write_lock(db)
    doc=document_access(db,document_id,user)
    db.scalar(select(Document.id).where(Document.id==document_id).with_for_update())
    ensure_active(db,'document',document_id)
    if doc.owner_id!=user.id and user.role!='super_admin':
        raise HTTPException(403,'只有资产所有者或管理员可调整元数据')
    require_base(db,doc.base_id,user)
    if data.folder_id:
        folder=db.get(Folder,data.folder_id)
        if not folder or folder.base_id!=doc.base_id:
            raise HTTPException(422,'目录不属于知识库')
    if data.requirement_id:
        owned(db.get(Requirement,data.requirement_id),user)
    if (doc.requirement_id!=data.requirement_id or doc.kind!=data.kind) and db.scalar(
        select(RequirementPackSpecification.id).where(RequirementPackSpecification.document_id==doc.id)
    ):
        raise HTTPException(409,'需求包软需的所属需求和文档类型不能调整')
    before=record(doc)
    for key,value in data.model_dump().items():
        setattr(doc,key,value)
    audit(db,user,'document.metadata',doc.id,before=before,after=record(doc))
    db.commit()
    return record(doc)


@router.get('/documents/{document_id}/impact')
def reference_impact(document_id: str,version_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    document_access(db,document_id,user)
    source=require_version(db,version_id,user)
    if source.document_id!=document_id:
        raise HTTPException(422,'版本不属于该文档')
    requirements=[record(r) for r in db.scalars(select(Requirement).where(Requirement.owner_id==user.id,Requirement.source_version_id==source.id)).all()]
    documents=[]
    for version in db.scalars(select(DocumentVersion)).all():
        if can_version(db,version,user) and any(c.get('document_version_id')==source.id for c in version.provenance.get('sources',[])):
            documents.append({'document_id':version.document_id,'version_id':version.id,'label':version.label,'status':version.status})
    knowledge=[]
    for revision in db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.source_version_id==source.id)).all():
        item=db.get(KnowledgeItem,revision.item_id)
        try:
            require_base(db,item.base_id,user)
        except HTTPException:
            continue
        knowledge.append({'item_id':item.id,'revision_id':revision.id,'name':item.name,'locator':revision.locator})
    runs=[{'run_id':run.id,'status':run.status} for run in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id)).all() if any(c.get('document_version_id')==source.id for c in run.citations)]
    return {'source_version_id':source.id,'requirements':requirements,'document_versions':documents,'knowledge_revisions':knowledge,'agent_runs':runs,'reason':'存在明确的版本引用；内容是否实际受影响仍需人工核对','requires_confirmation':True}


@router.post('/documents/upload')
async def upload(file: UploadFile=File(),title: str=Form(),base_id: str=Form(),label: str=Form('V1.0'),kind: str=Form('reference'),document_id: str | None=Form(None),folder_id: str | None=Form(None),requirement_id: str | None=Form(None),pack_id: str | None=Form(None),pack_stage: str | None=Form(None),user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..services.requirement_packs import STAGES, lock_requirement, pack_for, attach_versions
    data=await file.read(settings.upload_limit_mb*1024*1024+1)
    filename=validate(data,file.filename or '')
    pack=None
    if pack_id or pack_stage:
        if not pack_id or pack_stage not in STAGES or not requirement_id or document_id:
            raise HTTPException(422,'请选择当前需求、需求包和阶段以关联新文档')
        write_lock(db)
        lock_requirement(db,user,requirement_id)
        pack=pack_for(db,requirement_id,pack_id,persist=True)
    require_base(db,base_id,user)
    if not title.strip() or len(title)>300 or not label.strip() or len(label)>80:
        raise HTTPException(422,'标题或版本号无效')
    if folder_id:
        folder=db.get(Folder,folder_id)
        if not folder or folder.base_id!=base_id:
            raise HTTPException(422,'目录不属于目标知识库')
    if requirement_id:
        owned(db.get(Requirement,requirement_id),user)
        ensure_active(db,'requirement',requirement_id)
    if document_id:
        doc=document_access(db,document_id,user)
        ensure_active(db,'document',document_id)
        if doc.base_id!=base_id:
            raise HTTPException(422,'版本必须属于原知识库')
    else:
        doc=Document(title=title.strip(),base_id=base_id,owner_id=user.id,kind=kind,folder_id=folder_id,requirement_id=None if pack else requirement_id)
        db.add(doc)
        db.flush()
    if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id==doc.id,DocumentVersion.label==label)):
        raise HTTPException(409,'同一资产的版本号必须唯一')
    file_hash=store(data)
    version=DocumentVersion(document_id=doc.id,creator_id=user.id,label=label,filename=filename,file_hash=file_hash,parent_id=doc.current_version_id)
    db.add(version)
    db.flush()
    db.add(Outbox(kind='parse',resource_id=version.id))
    if pack:
        attach_versions(db,user,pack,pack_stage,[version])
    audit(db,user,'document.upload',version.id,file_hash=file_hash)
    db.commit()
    return {**record(version),'document_id':doc.id,'duplicate_content':bool(db.scalar(select(DocumentVersion.id).where(DocumentVersion.file_hash==file_hash,DocumentVersion.id!=version.id,DocumentVersion.creator_id==user.id)))}


@router.get('/documents/{document_id}/versions')
def versions(document_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    document_access(db,document_id,user)
    return [record(v,('content','blocks')) for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document_id).order_by(DocumentVersion.created_at.desc())).all() if can_version(db,v,user)]


@router.get('/documents/{document_id}/versions/{version_id}')
def version_detail(document_id: str,version_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    version=require_version(db,version_id,user)
    if version.document_id!=document_id:
        raise HTTPException(404,'版本不属于该文档')
    return record(version)


@router.post('/documents/{document_id}/versions')
@router.post('/documents/{document_id}/restore-draft')
def new_version(document_id: str,data: VersionInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    doc=document_access(db,document_id,user)
    ensure_active(db,'document',document_id)
    require_base(db,doc.base_id,user)
    source=require_version(db,data.source_version_id or doc.current_version_id,user) if data.source_version_id or doc.current_version_id else None
    if source and source.document_id!=doc.id:
        raise HTTPException(422,'源版本不属于该文档')
    if data.content is None and not source:
        raise HTTPException(422,'需要提供内容或源版本')
    if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id==doc.id,DocumentVersion.label==data.label)):
        raise HTTPException(409,'版本号已存在')
    content=data.content if data.content is not None else source.content
    provenance={'restored_from':source.id} if source else {}
    if doc.kind=='specification':
        images=image_ids(content)
        if images and (not source or set(images)-version_images(db,source).keys()):
            raise HTTPException(422,'只能保留源版本中的图片，请在软需编辑器中插入其他图片')
        if images: provenance['image_ids']=images
        if source and content==source.content and source.provenance.get('rich_text'):
            provenance['rich_text']=source.provenance['rich_text']
    file_hash=store(content.encode()) if data.content is not None else source.file_hash
    version=DocumentVersion(document_id=doc.id,creator_id=user.id,label=data.label,parent_id=source.id if source else None,filename=source.filename if source and data.content is None else doc.title+'.md',file_hash=file_hash,content=content,content_hash=digest(content),blocks=source.blocks if source and data.content is None else text_blocks(content),parse_status='ready',change_note=data.change_note,provenance=provenance)
    db.add(version)
    db.flush()
    audit(db,user,'version.create',version.id,parent_id=version.parent_id)
    db.commit()
    return record(version)


@router.patch('/versions/{version_id}')
def edit(version_id: str,data: EditVersion,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    version=require_version(db,version_id,user)
    version=db.scalar(select(DocumentVersion).where(DocumentVersion.id==version_id).with_for_update())
    ensure_active(db,'document',version.document_id)
    if version.creator_id!=user.id or version.status!='draft':
        raise HTTPException(403,'只能编辑自己未提交的草稿')
    if version.parse_status!='ready':
        raise HTTPException(409,'请等待解析完成')
    if version.revision!=data.expected_revision:
        raise HTTPException(409,'草稿已被修改，请重新加载')
    provenance={**version.provenance,'original_file_hash':version.provenance.get('original_file_hash',version.file_hash)}
    if db.get(Document,version.document_id).kind=='specification' and data.content!=version.content:
        images=image_ids(data.content)
        if images and set(images)-version_images(db,version).keys():
            raise HTTPException(422,'请在软需编辑器中插入新图片')
        provenance.pop('rich_text',None)
        provenance['image_ids']=images
    version.provenance=provenance
    version.file_hash=store(data.content.encode())
    version.filename=Path(version.filename).stem+'.md'
    version.content=data.content
    version.blocks=text_blocks(data.content)
    version.content_hash=digest(data.content)
    version.revision+=1
    audit(db,user,'version.edit',version.id,revision=version.revision)
    db.commit()
    return record(version)


@router.post('/versions/{version_id}/submit')
def submit(version_id: str,data: Submit,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return record(submit_review(db,user,version_id,data.reviewer_ids,data.note))


@router.post('/documents/batch-submit')
def submit_many(data: BatchSubmit,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return batch_submit(db,user,data)


@router.get('/versions/{version_id}/download')
def download(version_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    version=require_version(db,version_id,user)
    return FileResponse(blob(version.file_hash),filename=version.filename,media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})


@router.get('/versions/{version_id}/source-preview')
def preview(version_id: str, sheet: int=Query(-1, ge=-1), offset: int=Query(0, ge=0, le=1_048_575),
            user: User=Depends(current_user), db: Session=Depends(get_db)):
    version = require_version(db, version_id, user)
    result = source_preview(version.file_hash, version.filename, sheet=sheet, offset=offset)
    return {key: value for key, value in result.items() if key != 'images'}


def preview_image_response(image):
    return FileResponse(blob(image['hash']), media_type=image['type'],
                        headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})


@router.get('/versions/{version_id}/source-preview/image/{index}')
def preview_image(version_id: str, index: int, user: User=Depends(current_user), db: Session=Depends(get_db)):
    version = require_version(db, version_id, user)
    images = source_preview(version.file_hash, version.filename).get('images', [])
    if not 0 <= index < len(images):
        raise HTTPException(404, '图片不存在')
    return preview_image_response(images[index])


@router.get('/versions/{version_id}/source-preview/page/{page}')
def preview_page(version_id: str, page: int, user: User=Depends(current_user), db: Session=Depends(get_db)):
    version = require_version(db, version_id, user)
    if Path(version.filename).suffix.lower() != '.pdf':
        raise HTTPException(404, '页面不存在')
    metadata = source_preview(version.file_hash, version.filename)
    if not 1 <= page <= metadata['pages']:
        raise HTTPException(404, '页面不存在')
    return preview_image_response(source_preview(version.file_hash, version.filename, page=page))


@router.get('/versions/{version_id}/export')
def export(version_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    version=require_version(db,version_id,user)
    doc=db.get(Document,version.document_id)
    data=export_docx(doc,version,version_images(db,version))
    audit(db,user,'version.export',version.id,hash=digest(data))
    db.commit()
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="specification-{version.id}.docx"'})

@router.post('/versions/{version_id}/export-preview')
def preview_export(version_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    import json
    from ..services.export_preview import render
    version=require_version(db,version_id,user);doc=db.get(Document,version.document_id)
    data=export_docx(doc,version,version_images(db,version));db.commit()
    pdf,check=render(data)
    # Permissions are rechecked after rendering; no content changes or publication.
    require_version(db,version_id,user)
    audit(db,user,'version.export_preview',version_id,pages=check['pages'],warnings=check['warnings']);db.commit()
    return Response(pdf,media_type='application/pdf',headers={'Content-Disposition':'inline; filename="requirements-preview.pdf"','X-Export-Pages':str(check['pages']),'X-Export-Check':json.dumps(check,ensure_ascii=True),'Cache-Control':'no-store'})


@router.get('/documents/{document_id}/diff')
def diff(document_id: str,left: str,right: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    a=require_version(db,left,user)
    b=require_version(db,right,user)
    if a.document_id!=document_id or b.document_id!=document_id:
        raise HTTPException(422,'版本不属于文档')
    matcher=difflib.SequenceMatcher(a=[x['text'] for x in a.blocks],b=[x['text'] for x in b.blocks],autojunk=False)
    return [{'kind':tag,'left':a.blocks[i:j],'right':b.blocks[k:l]} for tag,i,j,k,l in matcher.get_opcodes()]


@router.get('/documents/{document_id}/history')
def history(document_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    document_access(db,document_id,user)
    ids=[v.id for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document_id)).all() if can_version(db,v,user)]
    return [record(a) for a in db.scalars(select(Audit).where(Audit.resource_id.in_(ids)).order_by(Audit.created_at)).all()]


@router.get('/documents/{document_id}/index-status')
def index_status(document_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    document_access(db,document_id,user)
    ids=[v.id for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document_id)).all() if can_version(db,v,user)]
    return [record(b) for b in db.scalars(select(IndexBuild).where(IndexBuild.version_id.in_(ids))).all()]


@router.post('/documents/{document_id}/reindex')
def reindex(document_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    doc=document_access(db,document_id,user)
    ensure_active(db,'document',document_id)
    if user.role!='super_admin' and doc.owner_id!=user.id:
        raise HTTPException(403,'只有所有者或管理员可重建索引')
    if not doc.current_version_id:
        raise HTTPException(409,'文档尚未发布')
    job=db.scalar(select(Outbox).where(Outbox.kind=='reindex',Outbox.resource_id==doc.current_version_id))
    if job and job.status=='running':
        raise HTTPException(409,'索引正在重建')
    if job:
        job.status='pending'
    else:
        db.add(Outbox(kind='reindex',resource_id=doc.current_version_id))
    audit(db,user,'index.rebuild',doc.current_version_id)
    db.commit()
    return {'queued':True}


@router.get('/index-builds/{build_id}')
def build_detail(build_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    build=db.get(IndexBuild,build_id)
    if not build:
        raise HTTPException(404,'索引不存在')
    require_version(db,build.version_id,user)
    return record(build)


@router.post('/index-builds/{build_id}/retry')
def build_retry(build_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    build=db.get(IndexBuild,build_id)
    if not build:
        raise HTTPException(404,'索引不存在')
    version=require_version(db,build.version_id,user)
    ensure_active(db,'document',version.document_id)
    if version.creator_id!=user.id and user.role!='super_admin':
        raise HTTPException(403,'仅创建人或管理员可重试')
    kind='publish' if version.publish_status!='published' else 'reindex'
    job=db.scalar(select(Outbox).where(Outbox.kind==kind,Outbox.resource_id==version.id))
    if not job or job.status=='running':
        raise HTTPException(409,'任务不存在或正在运行')
    job.status='pending'
    db.commit()
    return {'queued':True}


@router.post('/versions/{version_id}/retry-parse')
def parse_retry(version_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    version=require_version(db,version_id,user)
    ensure_active(db,'document',version.document_id)
    if version.creator_id!=user.id or version.status!='draft' or version.parse_status!='failed':
        raise HTTPException(403,'只能重试自己的解析失败草稿')
    job=db.scalar(select(Outbox).where(Outbox.kind=='parse',Outbox.resource_id==version_id))
    job.status='pending'
    version.parse_status='pending'
    db.commit()
    return {'queued':True}
