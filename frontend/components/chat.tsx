'use client';
import {AnswerEvidence,splitStoredAnswer} from './qa-controls';
import type {RetrievalMeta} from '../lib/types';
import {LedgerFillResult} from './ledger-fill-result';
import {DocumentChoices,useSelectableDocuments} from './document-choices';
import { useState, useRef, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles, Send, Square, Paperclip, Copy, RefreshCw, X, FileText, Pencil, Check } from 'lucide-react';
import { api, csrfHeaders, date } from '../lib/api';
import { readJsonResponse } from '../lib/http';
import type { User, Run, Message, Conversation, Base, Citation } from '../lib/types';
import type { PageKey } from './workbench';
import { Badge, Loading, Modal, FormModal, JsonView, useAction } from './ui';
import { DocumentPanel, UploadModal } from './knowledge';

export { SkillsPage } from './skills-page';

export function ChatPage({user,conversationId,setConversationId,navigate}:{user:User;conversationId:string;setConversationId:(id:string)=>void;navigate:(key:PageKey,id?:string)=>void}) {
 const [liveStatus,setLiveStatus]=useState<'generating'|'stopped'|'failed'|null>(null);const [provisional,setProvisional]=useState(false);const [liveReplyId,setLiveReplyId]=useState('');const [settlingUntil,setSettlingUntil]=useState(0);
 const pendingConversation=useRef('');const restoredContext=useRef(false);
 const followOutput=useRef(true);const messageArea=useRef<HTMLDivElement>(null);const [selectedRecord,setSelectedRecord]=useState<Citation|null>(null);
 const [retrieval,setRetrieval]=useState<RetrievalMeta|null>(null);
 const [candidateSources,setCandidateSources]=useState<Citation[]>([]);
 const [text,setText]=useState('');const [streaming,setStreaming]=useState('');const [busy,setBusy]=useState(false);const [sources,setSources]=useState<Citation[]>([]);const [attachmentIds,setAttachmentIds]=useState<string[]>([]);const [attach,setAttach]=useState(false);const [upload,setUpload]=useState(false);const [rename,setRename]=useState(false);const [selectedDocument,setSelectedDocument]=useState<{documentId:string;versionId:string}|null>(null);const abort=useRef<AbortController|null>(null);const {perform}=useAction();const queryClient=useQueryClient();
 const {data:messages=[]}=useQuery({queryKey:['messages',conversationId],queryFn:()=>api<Message[]>('/conversations/'+conversationId+'/messages'),enabled:!!conversationId,refetchInterval:()=>liveReplyId&&streaming&&liveStatus!=='generating'&&Date.now()<settlingUntil?1000:false});const {data:conversations=[]}=useQuery({queryKey:['conversations',false],queryFn:()=>api<Conversation[]>('/conversations')});const {data:documents=[]}=useSelectableDocuments();const {data:bases=[]}=useQuery({queryKey:['bases'],queryFn:()=>api<Base[]>('/knowledge-bases')});
 useEffect(()=>()=>abort.current?.abort(),[]);
 useEffect(()=>{if(!busy&&liveReplyId&&messages.some(m=>m.id===liveReplyId)){setLiveStatus(null);setStreaming('');}},[busy,liveReplyId,messages]);
 const lastQuestion=[...messages].reverse().find(message=>message.role==='user');
 useEffect(()=>{
   if(restoredContext.current||!lastQuestion)return;
   restoredContext.current=true;
   setAttachmentIds(lastQuestion.version_ids||[]);
 },[lastQuestion]);
 useEffect(()=>{const element=messageArea.current;if(element&&followOutput.current)element.scrollTop=element.scrollHeight;},[conversationId,messages.length,streaming,busy]);
 const conversation=conversations.find(c=>c.id===conversationId);
 const canRegenerate=lastQuestion&&!lastQuestion.skill_id&&(!lastQuestion.qa_mode||lastQuestion.qa_mode==='knowledge');
 async function send(regenerate=false) {
   if(busy)return;
   if(!text.trim()&&!regenerate)return;
   followOutput.current=true;setBusy(true);setStreaming('');setSources([]);setCandidateSources([]);setRetrieval(null);setLiveStatus('generating');setProvisional(false);setLiveReplyId('');
   const content=regenerate?lastQuestion?.content||'':text;
   let sentConversationId=conversationId||pendingConversation.current;
   let receivedText='',replyId='',stopped=false,accepted=false;
   const sent=await perform(async()=>{
    try{
     let id=sentConversationId;if(!id){const c=await api<Conversation>('/conversations','POST');id=c.id;pendingConversation.current=id;}sentConversationId=id;
     const controller=new AbortController();abort.current=controller;
     const response=await fetch('/api/conversations/'+id+'/messages',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json',...await csrfHeaders()},body:JSON.stringify({content,version_ids:attachmentIds,regenerate}),signal:controller.signal});
     if(!response.ok)await readJsonResponse(response);if(!response.body)throw new Error('无法读取响应流');
     accepted=true;setText('');const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='',doneSeen=false;
     while(true){
      const {value,done}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true});const frames=buffer.split('\n\n');buffer=frames.pop()||'';
      for(const frame of frames){
       if(!frame.startsWith('data: '))continue;
       const event=JSON.parse(frame.slice(6)) as {type:string;content?:string;message?:string;citations?:Citation[];meta?:RetrievalMeta;provisional?:boolean;candidate?:boolean};
       if(event.type==='retrieval'){setRetrieval(event.meta||null);if(event.meta?.reply_id){replyId=event.meta.reply_id;setLiveReplyId(replyId);}}
       if(event.type==='token'){receivedText+=event.content||'';setStreaming(receivedText);if(event.provisional!==undefined)setProvisional(event.provisional);}
       if(event.type==='answer'){receivedText=event.content||'';setStreaming(receivedText);setProvisional(false);}
       if(event.type==='sources'){
        if(event.candidate)setCandidateSources(event.citations||[]);
        else setSources(event.citations||[]);
       }
       if(event.type==='done')doneSeen=true;
       if(event.type==='error')throw new Error(event.message||'模型响应失败');
      }
     }
     if(!doneSeen)throw new Error('生成连接中断，已输出内容保留为未完成片段。');
     return true;
    }catch(error){
     stopped=error instanceof Error&&error.name==='AbortError';
     setLiveStatus(stopped?'stopped':'failed');setSources([]);setSettlingUntil(Date.now()+15000);
     if(!stopped&&!regenerate)setText(content);
     throw error;
    }
   },'响应已完成');
   setBusy(false);abort.current=null;
   if(sent){
    await queryClient.invalidateQueries({queryKey:['messages',sentConversationId]});
    if(!conversationId){pendingConversation.current='';setConversationId(sentConversationId);}
    setLiveStatus(null);setStreaming('');
   }else if(accepted){
    // The API finalizer may be saving the stopped fragment as the abort arrives.
    // Keep the live text visible until the stored reply with this ID is available.
    try{
     let saved=await queryClient.fetchQuery({queryKey:['messages',sentConversationId],queryFn:()=>api<Message[]>('/conversations/'+sentConversationId+'/messages'),staleTime:0});
     if(!conversationId&&replyId&&receivedText&&!saved.some(m=>m.id===replyId)){
      await new Promise(resolve=>setTimeout(resolve,250));
      saved=await queryClient.fetchQuery({queryKey:['messages',sentConversationId],queryFn:()=>api<Message[]>('/conversations/'+sentConversationId+'/messages'),staleTime:0});
     }
     if(!conversationId&&replyId&&saved.some(m=>m.id===replyId)){pendingConversation.current='';setConversationId(sentConversationId);}
    }catch{/* Keep the visible fragment if the service is disconnected. */}
   }
 }
 function openCitation(c:Citation){if(c.record_id){setSelectedRecord(c);return;}const d=documents.find(d=>d.versions.some(v=>v.id===c.document_version_id));if(c.document_version_id&&(c.document_id||d?.id))setSelectedDocument({documentId:c.document_id||d!.id,versionId:c.document_version_id});}
 return <section className="chat-workspace"><div className="chat-toolbar"><div><span className="file-icon"><MessageIcon/></span><strong>{conversation?.title||'新问答'}</strong>{conversation&&<button className="icon-button" title="重命名会话" onClick={()=>setRename(true)}><Pencil size={15}/></button>}</div><span className="muted small">带来源的知识问答</span></div><div className="chat-messages" ref={messageArea} onScroll={e=>{const element=e.currentTarget;followOutput.current=element.scrollHeight-element.scrollTop-element.clientHeight<100;}}>{!messages.length&&!busy&&<div className="chat-welcome"><span className="welcome-symbol"><Sparkles size={35}/></span><h1>知识问答</h1><p>输入问题，也可以附上相关文件。</p></div>}
 {messages.map(m=>{
  const {answer,originalQuotes}=m.role==='assistant'&&m.citations?.length
   ?splitStoredAnswer(m.content,m.qa_mode||m.retrieval?.qa_mode)
   :{answer:m.content,originalQuotes:[]};
  return <article className={'message '+m.role} key={m.id}><span className="message-avatar">{m.role==='user'?user.display_name[0]:<Sparkles size={17}/>}</span><div><div className="message-heading"><strong>{m.role==='user'?'您':'需求助手'}</strong><small>{date(m.created_at)}</small>{m.generation_status==='stopped'&&<span className="badge">已停止 · 部分内容</span>}{m.generation_status==='failed'&&<span className="badge returned">生成失败 · 部分内容</span>}{m.retrieval?.validation==='incomplete'&&<span className="badge returned">未完成来源校验</span>}</div>
   <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown></div>
   <AnswerEvidence meta={m.retrieval} citations={m.citations} candidates={m.candidate_citations} originalQuotes={originalQuotes} openCitation={openCitation}/><button className="text-button small" onClick={()=>void perform(()=>navigator.clipboard.writeText(answer),'内容已复制')}><Copy size={13}/>复制</button></div></article>;
 })}
 {(busy||liveStatus!==null)&&(!liveReplyId||!messages.some(m=>m.id===liveReplyId))&&<article className="message assistant live-reply"><span className="message-avatar"><Sparkles size={17}/></span><div><strong>需求助手</strong><span className="badge live-status">{liveStatus==='stopped'?'已停止 · 部分内容':liveStatus==='failed'?'生成失败 · 部分内容':provisional?'正在生成 · 来源待校验':'正在生成'}</span>{provisional&&liveStatus!=='generating'&&<span className="badge returned">未完成来源校验</span>}
  <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{streaming||(liveStatus==='failed'?'本次生成未完成，请重试。':liveStatus==='stopped'?'已停止生成。':retrieval?'正在生成回答…':'正在检索相关资料…')}</ReactMarkdown></div>
  <AnswerEvidence meta={retrieval} citations={sources} candidates={candidateSources} openCitation={openCitation}/>
 </div></article>}</div><div className="composer-container">{attachmentIds.length>0&&<div className="tag-list">{attachmentIds.map(id=><span className="attachment-tag" key={id}><FileText size={13}/>{documents.flatMap(d=>d.versions).find(v=>v.id===id)?.filename||id.slice(0,8)}<button onClick={()=>setAttachmentIds(attachmentIds.filter(v=>v!==id))}><X size={12}/></button></span>)}</div>}<form className="composer" onSubmit={e=>{e.preventDefault();void send();}}><textarea value={text} onChange={e=>setText(e.target.value)} placeholder="输入您的问题" rows={3} disabled={busy} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><div className="composer-actions"><button type="button" className="icon-button" title="附加需求文件" disabled={busy} onClick={()=>setAttach(true)}><Paperclip size={18}/></button><span className="spacer"/>{canRegenerate&&!busy&&<button type="button" className="icon-button" title="重新生成" onClick={()=>void send(true)}><RefreshCw size={17}/></button>}{busy?<button type="button" className="stop-button" onClick={()=>{abort.current?.abort();}}><Square size={15}/>停止</button>:<button className="send-button" disabled={!text.trim()} aria-label="发送消息"><Send size={18}/></button>}</div></form><small className="composer-note">请核对回答和引用来源。</small></div>{attach&&<Modal title="选择需求附件" close={()=>setAttach(false)}><div className="form-fields">{user.role!=='development_member'&&<button className="secondary" disabled={!bases.length} onClick={()=>setUpload(true)}><Paperclip size={15}/>上传新文件</button>}<DocumentChoices documents={documents} value={attachmentIds} max={10} onChange={setAttachmentIds}/><button className="primary" onClick={()=>setAttach(false)}>完成选择</button></div></Modal>}{upload&&bases.length>0&&<UploadModal bases={bases} defaultBase={bases[0].id} close={()=>setUpload(false)}/>} {rename&&conversation&&<FormModal title="重命名会话" fields={[{key:'title',label:'会话名称',required:true}]} initial={conversation} close={()=>setRename(false)} onSubmit={v=>perform(()=>api('/conversations/'+conversation.id,'PATCH',v))}/>} {selectedRecord&&<Modal title="业务记录来源" close={()=>setSelectedRecord(null)}><div className="form-fields"><strong>{selectedRecord.title}</strong><p className="notice">这是本次检索的业务登记快照，不能视为正式发布规则。当前记录可能已变化。</p><Badge state={selectedRecord.status||'draft'}/><pre className="qa-record-source">{selectedRecord.excerpt}</pre>{selectedRecord.record_kind==='requirement'&&<button className="secondary" onClick={()=>navigate('requirement',selectedRecord.record_id)}>查看当前需求</button>}{selectedRecord.record_kind==='agent_run'&&<button className="secondary" onClick={()=>navigate('task',selectedRecord.record_id)}>查看当前任务</button>}{user.role!=='development_member'&&selectedRecord.record_kind==='clarification_task'&&<button className="secondary" onClick={()=>navigate('clarification')}>前往澄清计划列表</button>}</div></Modal>} {selectedDocument&&<DocumentPanel user={user} documentId={selectedDocument.documentId} initialVersionId={selectedDocument.versionId} close={()=>setSelectedDocument(null)}/>}</section>;
}
function MessageIcon(){return <Sparkles size={17}/>;}

import {UmlResult} from './uml-skill';
import {PptReportResult} from './ppt-report-skill';
import {MindMapResult} from './mind-map-result';

export function RunPage({user,runId,navigate,openTaskResult}:{user:User;runId:string;navigate:(key:PageKey,id?:string)=>void;openTaskResult:(id:string)=>void}) {
 const {data:run,isLoading,error,isFetchedAfterMount}=useQuery({queryKey:['run',runId],queryFn:()=>api<Run>('/agent-runs/'+runId),enabled:!!runId,refetchOnMount:'always',refetchInterval:query=>['pending','running'].includes(query.state.data?.status||'')?2500:false});
 const lastStatus=useRef('');
 useEffect(()=>{if(run&&isFetchedAfterMount){if(lastStatus.current&&lastStatus.current!=='completed'&&run.status==='completed'&&(run.workflow||run.result.workflow)==='specification'&&run.inputs._specification_change_mode!=='partial')navigate('editor','run~'+run.id);lastStatus.current=run.status;}},[run,isFetchedAfterMount]);
 const [outline,setOutline]=useState<string|null>(null);const {perform}=useAction();const [busy,setBusy]=useState(false);
 if(isLoading||!isFetchedAfterMount)return <Loading/>;if(error)return <p className="form-error">{error.message}</p>;if(!run)return <p className="form-error">请选择一项执行记录</p>;
 const workflow=run.workflow||String(run.result.workflow||'');
 if(run.deleted_output)return <section className="panel"><h1>输出文档已删除</h1><p>历史执行记录保留，不能继续编辑已删除的文档。</p></section>;
 const initial=Array.isArray(run.result.outline)?run.result.outline.filter(item=>typeof item==='string').join('\n'):String(run.result.outline||'');
 const titles=(outline??initial).split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
 const analysis=(run.result.analysis||{}) as {answer?:string};const quality=(run.result.review||{}) as {answer?:string;items?:Record<string,unknown>[]};
 return <><div className="page-heading"><div><span className="eyebrow">{workflow==='specification'?'DOCUMENT GENERATION':'SKILL EXECUTION'}</span><h1>{workflow==='specification'?'需求文档生成':'技能执行结果'}</h1><p>{String(run.inputs.task)}</p></div><Badge state={run.status}/></div><section className="panel document-generation-status">{run.error&&<p className="form-error">{run.error}</p>}{run.status==='failed'&&<button className="secondary" onClick={()=>void perform(()=>api('/agent-runs/'+run.id+'/retry','POST'))}><RefreshCw size={15}/>重试未完成步骤</button>}{run.status==='awaiting_confirmation'&&<section className="outline-confirm"><h2>确认文档提纲</h2><p>每行一个章节标题，最多100项。确认后按照技能配置生成文档正文，随后进入编辑页面。</p><textarea aria-label="需求文档提纲" rows={14} value={outline??initial} onChange={event=>setOutline(event.target.value)}/><p className="muted small">当前 {titles.length} 项</p><button className="primary" disabled={busy||!titles.length||titles.length>100} onClick={async()=>{setBusy(true);await perform(()=>api('/agent-runs/'+run.id+'/resume','POST',{approved:true,outline:titles}),'提纲已确认，继续生成文档');setBusy(false);}}><Check size={16}/>{busy?'提交中…':'确认提纲并继续'}</button></section>}{['pending','running'].includes(run.status)&&<><Loading/><p className="muted">{workflow==='specification'?'正在按技能要求编制文档，完成后进入人工 / AI 编辑页面。':'正在执行技能任务。'}</p></>}{workflow==='specification'&&run.status==='completed'&&run.inputs._specification_change_mode==='partial'&&!run.result.local_change_application&&<button className="primary" onClick={()=>navigate('task',run.id)}>核对局部变更建议</button>}{workflow==='specification'&&run.status==='completed'&&run.inputs._specification_change_mode==='manual'&&<button className="primary" onClick={()=>navigate('editor','run~'+run.id)}>进入文档编辑工作台</button>}{workflow==='specification'&&run.status==='completed'&&run.inputs._specification_change_mode==='partial'&&!!run.result.local_change_application&&<button className="primary" onClick={()=>navigate('editor','run~'+run.id)}>继续编辑草稿</button>}{workflow==='specification'&&run.status==='completed'&&!['manual','partial'].includes(String(run.inputs._specification_change_mode))&&<><p className="notice">软需正文已生成。请进入独立工作台进行人工编辑、AI 问答和修改提案确认。</p><button className="primary" onClick={()=>navigate('editor','run~'+run.id)}>进入文档编辑工作台</button><details><summary>查看生成正文</summary><article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{run.document_content??((run.result.sections||[]) as {title:string;content:string}[]).map(s=>'# '+s.title+'\n'+s.content).join('\n\n')}</ReactMarkdown></article></details><details><summary>质量检查与覆盖情况</summary><article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{quality.answer||'尚无质量报告，请人工核对来源与正文。'}</ReactMarkdown></article>{!!quality.items?.length&&<div className="table-wrap"><table><thead><tr><th>来源需求</th><th>对应章节</th><th>覆盖情况</th></tr></thead><tbody>{quality.items.map((item,i)=><tr key={i}><td>{String(item.requirement||item.title||'待核对')}</td><td>{String(item.section||'待定位')}</td><td>{({covered:'已覆盖',missing:'缺失',uncertain:'待确认'} as Record<string,string>)[String(item.status)]||String(item.status||'待核对')}</td></tr>)}</tbody></table></div>}</details></>}{run.steps?.length>0&&<details><summary>执行过程（{run.steps.length} 步）</summary>{run.steps.map(step=><div className="version-row" key={step.id}><strong>{step.agent}</strong><p>{step.summary}</p></div>)}</details>}{workflow==='ledger_fill'&&run.status==='completed'&&<LedgerFillResult run={run} navigate={navigate}/>}
{workflow==='uml'&&run.status==='completed'&&<UmlResult run={run}/>}
{workflow==='ppt_report'&&run.status==='completed'&&<PptReportResult run={run}/>}
{workflow==='mind_map'&&run.status==='completed'&&<MindMapResult run={run}/>}
{!['specification','ledger_fill','clarification','uml','ppt_report','mind_map'].includes(workflow)&&analysis.answer&&<article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis.answer}</ReactMarkdown></article>}{!['specification','ledger_fill','uml','ppt_report','mind_map'].includes(workflow)&&['completed','awaiting_confirmation'].includes(run.status)&&<div className="notice"><button className="primary" onClick={()=>openTaskResult(run.id)}>查看本次分析结果</button></div>}</section></>;
}
