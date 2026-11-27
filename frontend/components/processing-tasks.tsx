'use client';
import {requirementLabel} from '../lib/business-identity';
import {useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {api,date} from '../lib/api';
import type {User,ProcessingTask,Requirement,Document,Version} from '../lib/types';
import type {PageKey} from './workbench';
import {SearchBox,SearchSelect,Badge,Empty,Loading,Tabs,Modal,FormModal,useAction} from './ui';
import {DeleteRecordButton} from './delete-record-button';
import {GenerationLauncher} from './generation-launcher';
import {DocumentPanel} from './knowledge';
import {canReviewCandidates,hasCandidates,TaskCandidates} from './task-candidates';
import {LedgerFillResult} from './ledger-fill-result';
import {RunPage} from './chat';
import {UmlResult} from './uml-skill';
import {PptReportResult} from './ppt-report-skill';
import {MindMapResult} from './mind-map-result';
import {SpecificationLocalChange,type LocalChangePlan} from './specification-local-change';
const workflowNames:Record<string,string>={mind_map:'思维导图生成',ppt_report:'一页汇报 PPT',uml:'UML 图生成',ledger_fill:'澄清台账填报',specification:'软需生成',clarification:'澄清分析',impact:'影响分析',qa:'知识问答',analysis:'需求解析',quality:'软需质检'};

export function ProcessingTasks({navigate,readOnly=false}:{navigate:(page:PageKey,id?:string)=>void;readOnly?:boolean}){
 const [q,setQ]=useState('');const [filter,setFilter]=useState('all');const [kind,setKind]=useState('all');const [generator,setGenerator]=useState(false);
 const {data:tasks=[],isLoading,error}=useQuery({queryKey:['processing-tasks'],queryFn:()=>api<ProcessingTask[]>('/processing-tasks'),refetchInterval:5000});
 const rows=tasks.filter(t=>(t.inputs.task+' '+(t.requirement?.number||'')+' '+(t.requirement?.title||'')+' '+t.id).toLowerCase().includes(q.toLowerCase())&&(kind==='all'||t.workflow===kind)&&(filter==='all'||filter==='unlinked'&&!t.requirement_id||filter==='active'&&['pending','running'].includes(t.status)||filter==='manual'&&['outline','editing','document_ready','analysis_ready'].includes(t.stage)||filter==='done'&&t.business_completed===true||filter==='failed'&&t.status==='failed'));
 return <><div className="toolbar task-toolbar"><SearchBox value={q} onChange={setQ} placeholder="搜索任务、需求编号或需求名称"/><SearchSelect aria-label="任务状态筛选" value={filter} onChange={e=>setFilter(e.target.value)}>{[{value:'all',label:'全部任务'},{value:'unlinked',label:'未关联需求'},{value:'active',label:'处理中'},{value:'manual',label:'待人工处理'},{value:'done',label:'业务已完成'},{value:'failed',label:'失败'}].map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</SearchSelect><SearchSelect aria-label="任务类型筛选" value={kind} onChange={e=>setKind(e.target.value)}><option value="all">全部技能</option>{Object.entries(workflowNames).map(([key,name])=><option key={key} value={key}>{name}</option>)}</SearchSelect>{!readOnly&&<button className="primary" onClick={()=>setGenerator(true)}>新建生成任务</button>}</div><p className="muted">技能任务独立保存，可在任务详情选择业务需求；同一需求可关联多个任务。</p>{error&&<p className="form-error">{error.message}</p>}{isLoading?<Loading/>:rows.length?<div className="table-wrap"><table><thead><tr><th>处理任务</th><th>技能类型</th><th>关联需求</th><th>处理状态</th><th>输出文档</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{rows.map(t=><tr key={t.id}><td><button className="text-button requirement-title" onClick={()=>navigate('task',t.id)}>{String(t.inputs.task)}</button><small className="block muted">TASK-{t.id.slice(0,8)}</small>{t.needs_review&&<span className="badge">历史归属待核对</span>}</td><td>{workflowNames[t.workflow]||t.skill_name}</td><td>{t.requirement?<button className="text-button" onClick={()=>navigate('requirement',t.requirement!.id)}>{t.requirement.number} {t.requirement.title}</button>:<span className="muted">未关联需求</span>}</td><td>{t.stage_label||t.status}</td><td>{t.output_count||0}</td><td><small>{date(t.created_at)}</small></td><td><div className="button-group"><button className="secondary" onClick={()=>navigate('task',t.id)}>任务详情</button>{!readOnly&&<DeleteRecordButton kind="agent_run" id={t.id} title={String(t.inputs.task)} disabledReason={t.status==='running'?'任务执行中，结束后可删除':undefined}/>}</div></td></tr>)}</tbody></table></div>:<Empty text="暂无符合条件的处理任务" detail="从技能库运行技能或创建生成任务，任务不会自动变成业务需求。"/>}{generator&&<GenerationLauncher close={()=>setGenerator(false)} navigate={navigate}/>}</>;
}

export function ProcessingTaskPage({user,id,navigate,activeTab,onTabChange:setTab,openRequirementAnalysis}:{user:User;id:string;navigate:(page:PageKey,id?:string)=>void;activeTab?:string;onTabChange:(tab:string)=>void;openRequirementAnalysis:(id:string)=>void}){
 const {perform}=useAction();const [repairBusy,setRepairBusy]=useState(false);const [associate,setAssociate]=useState(false);const [newRequirement,setNewRequirement]=useState(false);const [selectedId,setSelectedId]=useState('');const [associationRevision,setAssociationRevision]=useState(1);const [document,setDocument]=useState<{documentId:string;versionId:string}|null>(null);
 const {data:task,isLoading,error,refetch}=useQuery({queryKey:['processing-task',id],queryFn:()=>api<ProcessingTask>('/processing-tasks/'+id),refetchInterval:5000});
 const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements'),select:rows=>rows.filter(r=>r.can_edit!==false)});
 const [keepDocumentProcess,setKeepDocumentProcess]=useState(false);
 useEffect(()=>{
  if(task?.workflow==='specification'&&['pending','running','awaiting_confirmation'].includes(task.status))setKeepDocumentProcess(true);
 },[task?.workflow,task?.status]);
 if(isLoading)return <Loading/>;if(!task)return <p className="form-error">{error?.message||'任务不存在或未授权'}</p>;
 const isArtifactWorkflow=['uml','ppt_report','mind_map'].includes(task.workflow);
 const localChange=task.inputs._specification_change_mode==='partial';
 const localPlan=task.result.local_change as LocalChangePlan|undefined;
 const candidateReady=canReviewCandidates(task)&&hasCandidates(task);
 const defaultTab=keepDocumentProcess||['pending','running','awaiting_confirmation'].includes(task.status)?'process':
  task.status==='completed'&&task.workflow!=='specification'&&(candidateReady||task.workflow==='quality')?'analysis':'overview';
 const tab=activeTab==='requirements'?'analysis':activeTab||defaultTab;
 const initializationTask=Boolean(task.inputs._initialization_task||task.inputs._initialization||task.inputs._initialization_run_id);const locked=initializationTask||['pending','running'].includes(task.status);const groups=new Map<string,{document:Document;roles:Set<string>;versions:Map<string,Version>}>();
 for(const item of task.documents||[]){const group=groups.get(item.document.id)||{document:item.document,roles:new Set<string>(),versions:new Map<string,Version>()};group.roles.add(item.role);group.versions.set(item.version.id,item.version);groups.set(item.document.id,group);}
 const result=(task.workflow==='clarification'?{}:task.result.analysis||{}) as {answer?:string;items?:{title?:string;description?:string}[]};
 const impacts=(task.result.impact||{}) as {answer?:string;relations?:{description?:string;kind?:string}[]};
 const clarification=(task.result.clarification||{}) as {answer?:string};
 const summary=impacts.answer||clarification.answer||result.answer;
 if(user.role==='development_member'||task.read_only){
  const findings=[...(result.items||[]),...(impacts.relations||[])];
  const answers=[...new Set([result.answer,impacts.answer].filter((answer):answer is string=>Boolean(answer)))];
  return <>
   <div className="page-heading"><div><h1>{task.skill_name}</h1><p>{task.stage_label} · {date(task.created_at)}</p></div>
   </div>
   <section className="panel form-fields">
    {task.requirement&&<button className="text-button" onClick={()=>task.workflow==='clarification'?openRequirementAnalysis(task.requirement!.id):navigate('requirement',task.requirement!.id)}>{task.requirement.number} {task.requirement.title}</button>}
    <h3>分析结果</h3>
    {answers.map(answer=><article className="markdown" key={answer}><ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown></article>)}
    {findings.map((item,index)=><section className="question-card" key={index}><strong>{'title' in item?item.title:item.description}</strong>{'title' in item&&<p>{item.description}</p>}</section>)}
    {!findings.length&&!answers.length&&<p className="muted">暂无分析结果</p>}
    <h3>关联文档</h3>
    {task.documents?.map(item=><button className="workspace-row" key={item.role+item.version.id}
     onClick={()=>setDocument({documentId:item.document.id,versionId:item.version.id})}>{item.document.title} · {item.version.label}</button>)}
    {!task.documents?.length&&<p className="muted">暂无可查看的关联文档</p>}
   </section>
   {document&&<DocumentPanel user={user} documentId={document.documentId} initialVersionId={document.versionId} close={()=>setDocument(null)}/>}
  </>;
 }
 async function openAssociate(){if(!task)return;const refreshed=await refetch();const current=refreshed.data||task;setSelectedId(current.requirement_id||'');setAssociationRevision(current.task_revision);setAssociate(true);}
 return <><div className="page-heading"><div><span className="eyebrow">PROCESSING TASK</span><h1>{String(task.inputs.task)}</h1><p>TASK-{task.id.slice(0,8)} · {task.skill_name} · {date(task.created_at)}</p></div><div className="button-group"><DeleteRecordButton kind="agent_run" id={task.id} title={String(task.inputs.task)} onDeleted={()=>navigate('requirements','tasks')} disabledReason={task.status==='running'?'任务执行中，结束后可删除':undefined}/></div></div>
 <section className="panel task-association"><div><strong>{task.stage_label}</strong><p>{task.requirement?<><span>关联需求：</span><button className="text-button" onClick={()=>navigate('requirement',task.requirement!.id)}>{task.requirement.number} {task.requirement.title}</button></>:<span className="muted">未关联业务需求，任务及文档仍可独立保存。</span>}</p>{task.needs_review&&<p className="notice">历史记录已保留为需求，请核对它是否为真实业务需求；不会自动移动已有审核产物。</p>}</div><div className="button-group"><button className="secondary" disabled={locked} title={initializationTask?'初始化任务已绑定所属需求':locked?'任务执行结束后可调整关联':''} onClick={openAssociate}>{task.requirement_id?'更换关联需求':'关联业务需求'}</button><button className="secondary" disabled={locked} onClick={()=>{setAssociationRevision(task.task_revision);setNewRequirement(true);}}>新建需求并关联</button>{task.status==='completed'&&task.workflow==='specification'&&(!localChange||task.result.local_change_application)&&<button className="primary" onClick={()=>navigate('editor','run~'+task.id)}>继续编辑文档</button>}{task.status==='awaiting_confirmation'&&<button className="primary" onClick={()=>setTab('process')}>确认提纲</button>}</div></section>
 {localChange&&task.status==='completed'&&localPlan&&!task.result.local_change_application&&
  <SpecificationLocalChange id={task.id} plan={localPlan} openEditor={()=>navigate('editor','run~'+task.id)}/>}
 <section className="panel"><Tabs value={tab} onChange={setTab} items={[{key:'overview',label:'任务概览'},{key:'documents',label:'输入与输出文档'},...(isArtifactWorkflow?[]:[{key:'analysis',label:'分析结果'}]),{key:'process',label:'执行过程'}]}/>
 {task.workflow==='ledger_fill'&&task.status==='completed'&&tab!=='process'&&<LedgerFillResult run={task} navigate={navigate}/>}
 {tab==='overview'&&task.workflow==='uml'&&task.status==='completed'&&<UmlResult run={task}/>}
 {tab==='overview'&&task.workflow==='ppt_report'&&task.status==='completed'&&<PptReportResult run={task}/>}
 {tab==='overview'&&task.workflow==='mind_map'&&task.status==='completed'&&<MindMapResult run={task}/>}
 {tab==='overview'&&isArtifactWorkflow&&task.status!=='completed'&&<div className="form-fields">
  {task.error&&<p className="form-error">{task.error}</p>}
  <button className="secondary" onClick={()=>setTab('process')}>查看执行过程</button>
 </div>}
 {tab==='overview'&&!isArtifactWorkflow&&<div className="form-fields"><p>任务说明：{String(task.inputs.task)}</p><p>目标系统：{String(task.inputs.target_system||'未指定')}</p><p>技能类型：{workflowNames[task.workflow]} · 输出文档 {task.output_count} 份</p><p>文档版本确认后仍需按原流程提交审核。任务完成不会自动创建业务需求。</p><details><summary>执行过程与诊断</summary><button className="secondary" onClick={()=>setTab('process')}>查看执行记录</button></details>{task.error&&<p className="form-error">{task.error}</p>}{!task.inputs._initialization_run_id&&task.workflow!=='specification'&&task.workflow!=='ledger_fill'&&task.status==='completed'&&task.requirement_id&&!task.business_completed&&<button className="primary" onClick={()=>setTab('analysis')}>核对并确认分析</button>}</div>}
 {tab==='documents'&&<>{Array.from(groups.values()).map(group=>{const versions=Array.from(group.versions.values()).sort((a,b)=>b.created_at.localeCompare(a.created_at));return <section className="workspace-document" key={group.document.id}><div><h3>{group.document.title}</h3><p>{Array.from(group.roles).map(r=>({input:'业务输入',sample:'写作样例',template:'排版模板',output:'任务输出'}[r]||r)).join('、')} · {versions.length} 个关联版本</p>{versions.map(v=><button key={v.id} className="text-button" onClick={()=>setDocument({documentId:group.document.id,versionId:v.id})}>{v.label} · {v.status}　</button>)}</div><button className="secondary" onClick={()=>setDocument({documentId:group.document.id,versionId:versions[0].id})}>查看文档</button></section>})}{!groups.size&&<Empty text="尚无关联文档" detail="正文编辑草稿保存在工作台，确认版本后会显示为任务输出。"/>}</>}
 {tab==='analysis'&&task.workflow!=='ledger_fill'&&<div className="form-fields">{task.status==='completed'&&task.requirement_id&&['analysis','clarification','impact','quality'].includes(task.workflow)&&!task.inputs._initialization_run_id&&!task.result.saved_analysis_confirmed&&<button className="secondary" onClick={()=>void perform(()=>api('/processing-tasks/'+task.id+'/confirm-analysis','POST'),'分析已确认；后续相同来源与指令的任务可复用')}>确认分析供后续复用</button>}{task.workflow==='quality'&&task.status==='completed'&&(task.documents||[]).filter(d=>d.role==='input'&&d.document.kind==='specification'&&d.document.owner_id===user.id).map(d=><button className="secondary" disabled={repairBusy} key={d.version.id} onClick={async()=>{setRepairBusy(true);const result=await perform(()=>api<{version_id:string}>('/processing-tasks/'+task.id+'/repair-proposal','POST',{version_id:d.version.id}),'修复提案已生成，请核对右侧建议后确认应用');setRepairBusy(false);if(result)navigate('editor','version~'+result.version_id);}}>{repairBusy?'正在生成修复提案…':'根据报告修复：'+d.document.title}</button>)}{task.result.review&&<details open={task.workflow==='quality'}><summary>质量核查与覆盖报告</summary><article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{String((task.result.review as {answer?:string}).answer||'')}</ReactMarkdown></article></details>}{summary&&!candidateReady&&task.workflow!=='quality'&&<article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown></article>}
 {candidateReady&&<TaskCandidates key={activeTab==='requirements'?'requirements':'analysis'} run={task}
  requirementId={task.requirement_id} initialTab={activeTab==='requirements'?'requirements':undefined}/>}
 {!candidateReady&&!summary&&!task.result.review&&<Empty text={task.status==='completed'?'本次任务没有待核对候选':'分析结果尚未生成'}/>}
 {task.requirement&&candidateReady&&<button type="button" className="text-button" onClick={()=>openRequirementAnalysis(task.requirement!.id)}>查看需求的澄清与关联</button>}
 </div>}
 {tab==='process'&&<RunPage user={user} runId={task.id} navigate={navigate} openTaskResult={()=>setTab('analysis')}/>}</section>
 {associate&&<Modal title="关联业务需求" close={()=>setAssociate(false)}><div className="form-fields"><label>选择业务需求<SearchSelect aria-label="任务关联业务需求" value={selectedId} onChange={e=>setSelectedId(e.target.value)}><option value="">暂不关联需求</option>{requirements.filter(r=>!r.kind||r.kind==='business').map(r=><option key={r.id} value={r.id}>{requirementLabel(r)}</option>)}</SearchSelect></label>{!!task.requirement_candidates?.length&&<p className="notice">按编号匹配到：{task.requirement_candidates.map(r=><button className="text-button" key={r.id} onClick={()=>setSelectedId(r.id)}>{r.number} {r.title}</button>)}。请核对系统与项目后选择。</p>}<p className="notice">保存后，该任务会显示在所选需求的关联任务中。输入资料和写作样例的归属不变；已有审核产物的任务不能直接迁移。</p></div><footer><button className="secondary" onClick={()=>setAssociate(false)}>取消</button><button className="primary" onClick={async()=>{const saved=await perform(()=>api('/processing-tasks/'+task.id+'/requirement','PUT',{requirement_id:selectedId||null,expected_revision:associationRevision}),'任务关联已更新');if(saved)setAssociate(false);}}>保存关联</button></footer></Modal>}
 {newRequirement&&<FormModal title="新建业务需求并关联任务" fields={[{key:'number',label:'需求编号',required:true},{key:'title',label:'需求名称',required:true},{key:'description',label:'需求背景',type:'textarea'}]} close={()=>setNewRequirement(false)} onSubmit={v=>perform(()=>api('/processing-tasks/'+task.id+'/new-requirement','POST',{expected_revision:associationRevision,requirement:{...v,state:'draft'}}),'需求已创建并关联，任务记录继续保留')}/>}
 {document&&<DocumentPanel user={user} documentId={document.documentId} initialVersionId={document.versionId} close={()=>setDocument(null)}/>}</>;
}
