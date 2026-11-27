import re
from fastapi import APIRouter,Depends,File,HTTPException,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from typing import Literal
from sqlalchemy import or_,select,update
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import DocumentWorkspace as Workspace,DocumentAssistantMessage as Message,DocumentProposal as Proposal,DocumentChange as Change,Document,DocumentVersion,DocumentComment,DocumentImage,AgentRun,SkillVersion,User,Folder,ModelConfig,Requirement,now
from ..security import current_user,owned,can_version,require_version,require_base,write_lock,audit,digest
from ..serialize import record
from ..services.deletion import ensure_active
from ..services.richtext import rich_content
from ..services.files import blob,store,text_blocks
from ..services.document_images import MAX_IMAGE_BYTES,image_dimensions,workspace_image_ids
from ..services.ai import complete,model_config,SYSTEM_POLICY
from ..services.journey import context_for
from ..services.manuscript import assemble_sections,strip_citation_ids,clean_rich_document
from ..services.processing_tasks import linked_id,linked_requirement,link_document
from ..services.requirement_packs import assign_specification, lock_active_run_pack
from ..services.specification_revision import ApplyLocalChange, apply_local_change, next_version_label

router=APIRouter(tags=['文档编辑工作台'])

class OpenInput(BaseModel):
    run_id: str|None=None
    version_id: str|None=None

class DraftInput(BaseModel):
    expected_revision: int
    content_json: dict
    title: str=Field(min_length=1,max_length=300)
    label: str=Field(min_length=1,max_length=80)
    base_id: str|None=None
    folder_id: str|None=None
    change_note: str=Field(default='',max_length=10000)

class AssistInput(BaseModel):
    expected_revision: int
    mode: Literal['ask','modify']
    instruction: str=Field(min_length=1,max_length=3000)
    selected_text: str=Field(default='',max_length=20000)
    block_from: int|None=Field(default=None,ge=0)
    block_to: int|None=Field(default=None,ge=0)
    proposal_id: str|None=None

class PreviewInput(BaseModel):
    content_json: dict

class ApplyInput(PreviewInput):
    expected_revision: int
    confirm: Literal[True]

class RevisionInput(BaseModel):
    expected_revision: int


class CommentAnchor(BaseModel):
    offset: int=Field(ge=0,le=8_000_000)
    before: str=Field(default='',max_length=64)
    after: str=Field(default='',max_length=64)


class CommentInput(BaseModel):
    content: str=Field(min_length=1,max_length=4000)
    quote: str=Field(default='',max_length=2000)
    anchor: CommentAnchor|None=None

def active(db,w,user):
    if w.run_id and not w.document_id: ensure_active(db,'agent_run',w.run_id)
    if w.document_id:
        ensure_active(db,'document',w.document_id)
        doc=db.get(Document,w.document_id)
        if doc.owner_id!=user.id: raise HTTPException(403,'只有文档所有者可编辑此工作草稿')
        require_base(db,doc.base_id,user)
    if w.requirement_id: ensure_active(db,'requirement',w.requirement_id)
    return w

def access(db,id,user,lock=False):
    q=select(Workspace).where(Workspace.id==id)
    w=owned(db.scalar(q.with_for_update().execution_options(populate_existing=True) if lock else q),user)
    return active(db,w,user)

def check_revision(w,expected):
    if w.revision!=expected: raise HTTPException(409,'文档已发生变化，请保存本页内容并重新打开工作台核对；旧提案不能覆盖新内容')

def bundle(db,w):
    messages=db.scalars(select(Message).where(Message.workspace_id==w.id).order_by(Message.created_at)).all()
    proposals=db.scalars(select(Proposal).where(Proposal.workspace_id==w.id).order_by(Proposal.created_at)).all()
    return {**record(w),'messages':[record(m) for m in messages],'proposals':[record(p) for p in proposals]}

@router.post('/document-workspaces/open')
def open_workspace(data:OpenInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db)
    if bool(data.run_id)==bool(data.version_id): raise HTTPException(422,'请选择执行结果或文档版本')
    run=None;version=None;doc=None
    if data.run_id:
        run=owned(db.get(AgentRun,data.run_id),user);ensure_active(db,'agent_run',run.id)
        if run.status!='completed' or db.get(SkillVersion,run.skill_version_id).config['workflow']!='specification': raise HTTPException(409,'软需正文生成完成后可进入编辑工作台；旧问答任务请重新生成')
        if run.inputs.get('_specification_change_mode')=='partial' and not run.result.get('local_change_application'):
            raise HTTPException(409,'请先在任务详情核对局部变更建议')
        version=require_version(db,run.result['saved_version_id'],user) if run.result.get('saved_version_id') else None
    else:
        version=require_version(db,data.version_id,user)
        doc=db.get(Document,version.document_id)
        if doc.owner_id!=user.id: raise HTTPException(403,'只有文档所有者可创建编辑草稿')
    if version:
        doc=db.get(Document,version.document_id);ensure_active(db,'document',doc.id)
        # The same document always resumes the same working copy, including list entry points.
        q=select(Workspace).where(Workspace.owner_id==user.id,Workspace.document_id==doc.id)
        if run and run.inputs.get('_specification_baseline_id'):
            q=q.where(Workspace.run_id==run.id)
        w=db.scalar(q.order_by((Workspace.version_id==version.id).desc(),Workspace.updated_at.desc()))
        if w:
            active(db,w,user);db.commit();return bundle(db,w)
    key='run:'+run.id if run else 'document:'+doc.id
    w=db.scalar(select(Workspace).where(Workspace.owner_id==user.id,Workspace.origin_key==key))
    if w:
        active(db,w,user);db.commit();return bundle(db,w)
    draft=run.result.get('editor_draft',{}) if run else {}
    content=draft.get('content',version.content if version else assemble_sections(run.result.get('sections',[])))
    label=next_version_label(version.label) if version else 'V1.0'
    if run and not version and run.inputs.get('_specification_baseline_id'):
        version=require_version(db,run.inputs['_specification_baseline_id'],user)
        doc=db.get(Document,version.document_id)
        if doc.requirement_id!=linked_id(db,run) or doc.owner_id!=user.id:
            raise HTTPException(409,'基线文档的归属已更改')
        labels=set(db.scalars(select(DocumentVersion.label).where(DocumentVersion.document_id==doc.id)))
        label=next_version_label(version.label)
        while label in labels:
            label=next_version_label(label)
    w=Workspace(owner_id=user.id,origin_key=key,run_id=run.id if run else None,document_id=doc.id if doc else None,version_id=version.id if version else None,requirement_id=linked_id(db,run) if run else doc.requirement_id,title=draft.get('title') or (doc.title if doc else '软件需求说明书'),label=draft.get('label') or label,base_id=doc.base_id if doc else draft.get('base_id') or None,folder_id=doc.folder_id if doc else draft.get('folder_id') or None,content=content,content_json=(version.provenance.get('rich_text') if version and content==version.content else None),change_note=draft.get('change_note') or (run.inputs.get('_specification_change_note','') if run else ''),sources=(run.citations if run else version.provenance.get('sources',[])))
    active(db,w,user);db.add(w);db.flush();audit(db,user,'workspace.open',w.id,run_id=w.run_id,version_id=w.version_id);db.commit();return bundle(db,w)

@router.get('/document-workspaces/{id}')
def get_workspace(id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return bundle(db,access(db,id,user))


@router.post('/agent-runs/{run_id}/apply-local-change')
def apply_specification_local_change(run_id:str,data:ApplyLocalChange,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db)
    run=owned(db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update()),user)
    ensure_active(db,'agent_run',run_id)
    lock_active_run_pack(db,linked_id(db,run),run.inputs)
    workspace=apply_local_change(db,user,run,data.changes)
    db.commit()
    return {'workspace_id':workspace.id}


def specification_version(db, version_id, user):
    version=require_version(db,version_id,user)
    if db.get(Document,version.document_id).kind!='specification':
        raise HTTPException(404,'软需版本不存在')
    return version


def specification_workspace(db, workspace_id, user, lock=False):
    workspace=access(db,workspace_id,user,lock)
    if workspace.document_id and db.get(Document,workspace.document_id).kind!='specification':
        raise HTTPException(404,'软需草稿不存在')
    return workspace


def workspace_comments(workspace):
    return or_(DocumentComment.workspace_id==workspace.id,
               DocumentComment.version_id==workspace.version_id) if workspace.version_id else DocumentComment.workspace_id==workspace.id


def list_comments(db, scope):
    rows=db.execute(select(DocumentComment,User.display_name).join(User,User.id==DocumentComment.author_id)
                    .where(scope).order_by(DocumentComment.created_at,DocumentComment.id))
    return [{**record(comment),'author_name':name} for comment,name in rows]


def add_comment(db,user,data,*,version_id=None,workspace_id=None):
    text=data.content.strip()
    if not text:
        raise HTTPException(422,'请输入批注内容')
    quote=data.quote.strip()
    anchor=data.anchor.model_dump() if quote and data.anchor else None
    comment=DocumentComment(version_id=version_id,workspace_id=workspace_id,author_id=user.id,quote=quote,anchor=anchor,content=text)
    db.add(comment);db.flush()
    audit(db,user,'document.comment',comment.id,version_id=version_id,workspace_id=workspace_id)
    db.commit()
    return {**record(comment),'author_name':user.display_name}


def delete_comment(db,user,scope,comment_id):
    comment=db.scalar(select(DocumentComment).where(DocumentComment.id==comment_id,scope).with_for_update())
    if not comment:
        raise HTTPException(404,'批注不存在')
    if comment.author_id!=user.id:
        raise HTTPException(403,'只能删除自己的批注')
    db.delete(comment);audit(db,user,'document.comment_delete',comment_id);db.commit()
    return {'ok':True}


@router.get('/document-workspaces/{id}/comments')
def list_workspace_comments(id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return list_comments(db,workspace_comments(specification_workspace(db,id,user)))


@router.post('/document-workspaces/{id}/comments')
def add_workspace_comment(id:str,data:CommentInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);w=specification_workspace(db,id,user,True)
    version=db.get(DocumentVersion,w.version_id) if w.version_id else None
    if version and w.content==version.content:
        return add_comment(db,user,data,version_id=version.id)
    return add_comment(db,user,data,workspace_id=id)


@router.delete('/document-workspaces/{id}/comments/{comment_id}')
def delete_workspace_comment(id:str,comment_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db)
    return delete_comment(db,user,workspace_comments(specification_workspace(db,id,user,True)),comment_id)


@router.get('/versions/{id}/comments')
def list_version_comments(id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    specification_version(db,id,user)
    return list_comments(db,DocumentComment.version_id==id)


@router.post('/versions/{id}/comments')
def add_version_comment(id:str,data:CommentInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    specification_version(db,id,user)
    return add_comment(db,user,data,version_id=id)


@router.delete('/versions/{id}/comments/{comment_id}')
def delete_version_comment(id:str,comment_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);specification_version(db,id,user)
    return delete_comment(db,user,DocumentComment.version_id==id,comment_id)


@router.post('/document-workspaces/{id}/images')
async def upload_image(id:str,file:UploadFile=File(),user:User=Depends(current_user),db:Session=Depends(get_db)):
    w=specification_workspace(db,id,user)
    data=await file.read(MAX_IMAGE_BYTES+1)
    if not data or len(data)>MAX_IMAGE_BYTES:
        raise HTTPException(413,'图片不能为空，且大小不能超过 10 MB')
    media_type,width,height=image_dimensions(data)
    filename=(file.filename or '图片').replace('\\','/').rsplit('/',1)[-1][:300]
    image=DocumentImage(workspace_id=w.id,file_hash=store(data),filename=filename,media_type=media_type,width=width,height=height)
    db.add(image);db.flush();audit(db,user,'workspace.image_upload',image.id,workspace_id=w.id);db.commit()
    return {'src':'/api/document-images/'+image.id,'alt':filename}


@router.get('/document-images/{id}')
def get_image(id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    image=db.get(DocumentImage,id)
    if not image:
        raise HTTPException(404,'图片不存在或未授权')
    workspace=db.get(Workspace,image.workspace_id)
    allowed=False
    if workspace.owner_id==user.id:
        try:
            active(db,workspace,user)
            allowed=True
        except HTTPException as error:
            if error.status_code not in (403,404,410): raise
    if not allowed and workspace.document_id:
        versions=db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==workspace.document_id))
        allowed=any(id in version.provenance.get('image_ids',[]) and can_version(db,version,user) for version in versions)
    path=blob(image.file_hash)
    if not allowed or not path.is_file():
        raise HTTPException(404,'图片不存在或未授权')
    return FileResponse(path,media_type=image.media_type,headers={'Cache-Control':'private, no-store'})


@router.put('/document-workspaces/{id}')
def save_draft(id:str,data:DraftInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    tree,text=rich_content(data.content_json)
    write_lock(db);w=access(db,id,user,True);check_revision(w,data.expected_revision)
    workspace_image_ids(db,w,text)
    if data.base_id: require_base(db,data.base_id,user)
    if w.document_id and data.base_id!=db.get(Document,w.document_id).base_id: raise HTTPException(422,'修订稿应保存在原知识库')
    if data.folder_id:
        folder=db.get(Folder,data.folder_id)
        if not folder or folder.base_id!=data.base_id: raise HTTPException(422,'目录不属于所选知识库')
    if w.content_json!=tree:
        db.add(Change(workspace_id=id,actor_id=user.id,revision=w.revision+1,before_json=w.content_json,after_json=tree,before_content=w.content,after_content=text))
    for key in ('title','label','base_id','folder_id','change_note'): setattr(w,key,getattr(data,key))
    w.content_json=tree;w.content=text;w.revision+=1;w.updated_at=now()
    db.commit();return record(w)

@router.post('/document-workspaces/{id}/assistant')
def assistant(id:str,data:AssistInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    w=access(db,id,user);check_revision(w,data.expected_revision)
    if len(w.content)>200000: raise HTTPException(422,'当前 AI 编辑支持最多20万字，请缩小文档内容')
    if data.selected_text and data.selected_text not in w.content and not w.content_json: raise HTTPException(422,'选中内容不属于当前文档')
    snapshot=record(w);run=db.get(AgentRun,w.run_id) if w.run_id else None
    target=w.content;scope={'scope':'document'}
    if data.block_from is not None or data.block_to is not None:
        nodes=(w.content_json or {}).get('content',[])
        if data.block_from is None or data.block_to is None or not 0<=data.block_from<data.block_to<=len(nodes):raise HTTPException(422,'选中段落范围无效，请重新选择')
        _,target=rich_content({'type':'doc','content':nodes[data.block_from:data.block_to]})
        scope={'scope':'blocks','block_from':data.block_from,'block_to':data.block_to}
    prior_proposal=None
    if data.proposal_id:
        prior_proposal=get_proposal(db,w,data.proposal_id)
        if prior_proposal.status!='pending' or prior_proposal.base_revision!=w.revision:raise HTTPException(409,'提案已处理或正文已变化')
        scope={k:prior_proposal.detail[k] for k in ('scope','block_from','block_to') if k in prior_proposal.detail}
        target=rich_content(prior_proposal.preview_json)[1] if prior_proposal.preview_json else prior_proposal.suggested_content
    skill=db.get(SkillVersion,run.skill_version_id) if run else None
    model=db.get(ModelConfig,run.model_trace.get('model_config_id')) if run and run.model_trace.get('model_config_id') else None
    if not model or not model.enabled: model=model_config(db)
    history=db.scalars(select(Message).where(Message.workspace_id==id,Message.mode=='ask').order_by(Message.created_at.desc()).limit(8)).all()
    policy='你是文档工作台助手。模板仅提供结构和写法，业务事实只采用本次来源与已确认澄清。'
    policy+=('只回答问题，指出依据、歧义和待确认事项，不修改正文。' if data.mode=='ask' else '只返回修改后的完整文档 Markdown 正文，不加解释或代码围栏。保持未要求修改的章节和业务内容，不编造规则；未知业务口径标为待确认。')
    if data.mode=='modify':policy+='原有图片使用 Markdown 语法引用，保留未要求删除的图片及其位置和链接。'
    policy+='正文和回答不输出 [citation_id:...]、UUID 等内部引用标记；引用依据只用文件名称描述。章节标题按编号层级输出且同一标题只出现一次。'
    if scope['scope']=='blocks':policy+='本次仅修改 target_untrusted 中的段落，只返回这些段落的修改后 Markdown，不输出全文或其他章节。'
    messages=[{'role':'system','content':SYSTEM_POLICY+'\n'+(skill.config.get('system_prompt','') if skill else '')+'\n'+policy}]
    messages += [{'role':m.role,'content':m.content[:6000]} for m in reversed(history)] if data.mode=='ask' else []
    messages.append({'role':'user','content':__import__('json').dumps({'instruction':data.instruction,'document_untrusted':w.content,'target_untrusted':target,'selected_context_untrusted':data.selected_text,'evidence_untrusted':w.sources},ensure_ascii=False)})
    # Release the read transaction before the remote call; never hold a document write lock.
    db.commit()
    answer,trace=complete(db,user.id,messages,config=model,temperature=0.2)
    if not answer.strip() or len(answer)>2000000: raise HTTPException(502,'模型返回空内容或内容超过限制')
    if data.mode=='modify': answer=re.sub(r'^```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$',r'\1',answer.strip())
    answer=strip_citation_ids(answer)
    db.commit();write_lock(db);w=access(db,id,user,True)
    proposal=None
    if data.mode=='modify':
        original=prior_proposal.before_content if prior_proposal else (target if scope['scope']=='blocks' else snapshot['content'])
        proposal=Proposal(workspace_id=id,base_revision=snapshot['revision'],before_content=original,suggested_content=answer,status='pending' if w.revision==snapshot['revision'] else 'stale',detail={'instruction':data.instruction,**scope,'trace':trace,'parent_proposal_id':data.proposal_id})
        db.add(proposal);db.flush()
    db.add(Message(workspace_id=id,role='user',mode=data.mode,content=data.instruction,detail={'revision':snapshot['revision'],'selected_text':data.selected_text}))
    reply=answer if data.mode=='ask' else '已生成'+('所选段落' if scope['scope']=='blocks' else '全文')+'修改提案。请查看修改前后内容，可先调整建议再确认应用。'
    m=Message(workspace_id=id,role='assistant',mode=data.mode,content=reply,detail={'proposal_id':proposal.id if proposal else None,'trace':trace})
    db.add(m);audit(db,user,'workspace.assistant',id,mode=data.mode,proposal_id=proposal.id if proposal else None);db.commit()
    return {'message':record(m),'proposal':record(proposal) if proposal else None}

def get_proposal(db,w,pid):
    p=db.scalar(select(Proposal).where(Proposal.id==pid,Proposal.workspace_id==w.id).with_for_update())
    if not p: raise HTTPException(404,'修改提案不存在')
    return p

@router.post('/document-workspaces/{id}/format-proposal')
def format_proposal(id:str,data:RevisionInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);w=access(db,id,user,True);check_revision(w,data.expected_revision)
    if not w.content_json: raise HTTPException(409,'请先保存富文本正文')
    tree,issues=clean_rich_document(w.content_json);tree,text=rich_content(tree)
    p=Proposal(workspace_id=id,base_revision=w.revision,before_content=w.content,suggested_content=text,preview_json=tree,detail={'kind':'formatting_cleanup','issues':issues,'note':'整理标题与内部引用，移除完全相同的重复章节正文；有差异的业务内容保留。'})
    db.add(p);db.flush();audit(db,user,'workspace.format_proposal',p.id,issues=issues);db.commit();return record(p)

@router.put('/document-workspaces/{id}/proposals/{pid}')
def preview(id:str,pid:str,data:PreviewInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    tree,text=rich_content(data.content_json);write_lock(db);w=access(db,id,user,True);p=get_proposal(db,w,pid)
    workspace_image_ids(db,w,text)
    if p.status!='pending': raise HTTPException(409,'提案已处理或过期')
    p.preview_json=tree;db.commit();return record(p)

@router.post('/document-workspaces/{id}/proposals/{pid}/discard')
def discard(id:str,pid:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);w=access(db,id,user,True);p=get_proposal(db,w,pid)
    if p.status=='applied': raise HTTPException(409,'提案已应用')
    p.status='discarded';audit(db,user,'workspace.proposal_discard',pid);db.commit();return record(p)

@router.post('/document-workspaces/{id}/proposals/{pid}/apply')
def apply(id:str,pid:str,data:ApplyInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    tree,text=rich_content(data.content_json)
    if not text.strip(): raise HTTPException(422,'不能应用空文档')
    write_lock(db);w=access(db,id,user,True);p=get_proposal(db,w,pid)
    if p.status=='applied': return {'already_applied':True,'workspace':record(w),'proposal':record(p)}
    check_revision(w,data.expected_revision)
    if p.status!='pending' or p.base_revision!=w.revision: raise HTTPException(409,'正文已变化或提案已处理，请重新生成修改提案')
    preview_tree=tree
    if p.detail.get('scope')=='blocks':
        nodes=w.content_json['content'];start=p.detail['block_from'];end=p.detail['block_to']
        tree,text=rich_content({'type':'doc','content':nodes[:start]+tree.get('content',[])+nodes[end:]})
    workspace_image_ids(db,w,text)
    db.add(Change(workspace_id=id,actor_id=user.id,proposal_id=p.id,revision=w.revision+1,before_json=w.content_json,after_json=tree,before_content=w.content,after_content=text))
    w.content_json=tree;w.content=text;w.revision+=1;w.updated_at=now();p.preview_json=preview_tree;p.status='applied'
    audit(db,user,'workspace.proposal_apply',p.id,revision=w.revision);db.commit();return {'workspace':record(w),'proposal':record(p)}

@router.post('/document-workspaces/{id}/confirm')
def confirm(id:str,data:RevisionInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);w=access(db,id,user,True);check_revision(w,data.expected_revision)
    if not w.content_json or not w.content.strip() or not w.base_id: raise HTTPException(422,'请先保存正文、文档名称、版本号和知识库')
    require_base(db,w.base_id,user)
    run=db.scalar(select(AgentRun).where(AgentRun.id==w.run_id).with_for_update()) if w.run_id else None
    initialized=bool(run and (run.inputs.get('_requirement_pack_id') or run.inputs.get('_initialization_task') or run.inputs.get('_initialization')))
    if w.confirmed_revision==w.revision and w.version_id:
        return {**record(db.get(DocumentVersion,w.version_id)),'requirement_id':w.requirement_id,'return_to_requirement':initialized}
    if run: w.requirement_id=linked_id(db,run)
    if w.document_id:
        doc=db.scalar(select(Document).where(Document.id==w.document_id).with_for_update())
        if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id==doc.id,DocumentVersion.label==w.label)): raise HTTPException(409,'版本号已存在，请填写新的版本号')
    else:
        doc=Document(owner_id=user.id,title=w.title,base_id=w.base_id,folder_id=w.folder_id,requirement_id=w.requirement_id,kind='specification')
        db.add(doc);db.flush();w.document_id=doc.id
    from ..services.delivery import contract,quality
    cfg=db.get(SkillVersion,run.skill_version_id).config if run else {}
    template_id=run.inputs.get('word_template_version_id') if run else None
    if template_id:require_version(db,template_id,user)
    baseline=db.get(DocumentVersion,run.inputs.get('_specification_baseline_id')) if run and run.inputs.get('_specification_baseline_id') else None
    delivery=(baseline.provenance.get('delivery_template') if baseline else None) or contract(cfg)
    images=workspace_image_ids(db,w,w.content)
    assign_specification(db,run,doc)
    version=DocumentVersion(document_id=doc.id,creator_id=user.id,parent_id=w.version_id,label=w.label,filename=w.title+'.md',content=w.content,file_hash=store(w.content.encode()),content_hash=digest(w.content),blocks=text_blocks(w.content),parse_status='ready',change_note=w.change_note or '文档工作台人工确认',provenance={'workspace_id':w.id,'agent_run_id':w.run_id,'sources':w.sources,'rich_text':w.content_json,'image_ids':images,'human_edited':True,'delivery_template':delivery,'word_template_version_id':template_id,'structure_check':quality(w.content,delivery),'coverage':run.result.get('review',{}).get('items',[]) if run else [],'change_baseline_version_id':run.inputs.get('_specification_baseline_id') if run else None})
    db.add(version);db.flush();w.version_id=version.id;w.confirmed_revision=w.revision
    db.execute(update(DocumentComment).where(DocumentComment.workspace_id==w.id).values(workspace_id=None,version_id=version.id))
    if run:
        link_document(db,run,version.id)
        run.result={**run.result,'saved_version_id':version.id,'saved_version_ids':list(dict.fromkeys([*run.result.get('saved_version_ids',[]),version.id]))}
    if w.requirement_id:
        requirement=owned(db.get(Requirement,w.requirement_id),user);ctx=context_for(db,requirement)
        if requirement.state!='published': requirement.state='specified';requirement.revision+=1
    audit(db,user,'workspace.confirm_version',version.id,workspace_id=w.id,revision=w.revision);db.commit()
    return {**record(version),'requirement_id':w.requirement_id,'return_to_requirement':initialized}

@router.get('/document-workspaces/{id}/history')
def history(id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    access(db,id,user)
    return [record(c,('before_json','after_json','before_content','after_content')) for c in db.scalars(select(Change).where(Change.workspace_id==id).order_by(Change.created_at.desc())).all()]

@router.post('/document-workspaces/{id}/restore-proposal/{change_id}')
def restore_proposal(id:str,change_id:str,data:RevisionInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);w=access(db,id,user,True);check_revision(w,data.expected_revision)
    c=db.get(Change,change_id)
    if not c or c.workspace_id!=id:raise HTTPException(404,'历史记录不存在')
    p=Proposal(workspace_id=id,base_revision=w.revision,before_content=w.content,suggested_content=c.after_content,preview_json=c.after_json,detail={'kind':'history_restore','change_id':c.id})
    db.add(p);db.flush();audit(db,user,'workspace.restore_proposal',p.id,change_id=c.id);db.commit();return record(p)

@router.post('/document-workspaces/{id}/proposals/{pid}/diff')
def proposal_diff(id:str,pid:str,data:PreviewInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    import difflib
    w=access(db,id,user);p=get_proposal(db,w,pid);_,after=rich_content(data.content_json)
    left=p.before_content.splitlines();right=after.splitlines()
    return [{'kind':kind,'before':left[a:b],'after':right[c:d]} for kind,a,b,c,d in difflib.SequenceMatcher(None,left,right,autojunk=False).get_opcodes()]

@router.post('/document-workspaces/{id}/quality')
def quality_check(id:str,data:RevisionInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    w=access(db,id,user);check_revision(w,data.expected_revision)
    from ..services.delivery import quality,contract
    run=db.get(AgentRun,w.run_id) if w.run_id else None
    skill=db.get(SkillVersion,run.skill_version_id) if run else None
    report=quality(w.content,contract(skill.config if skill else {}))
    return {'revision':w.revision,**report}
