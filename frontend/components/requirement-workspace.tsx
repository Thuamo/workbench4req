'use client';
import {useState,useEffect} from 'react';
import {useQuery} from '@tanstack/react-query';
import {ChevronDown, ChevronRight, FileText, Folder, Plus} from 'lucide-react';
import {api,date,states} from '../lib/api';
import {versionStage} from '../lib/journey';
import type {User,Requirement,Document,Version,ProcessingTask,Question,Review,Base} from '../lib/types';
import type {PageKey} from './workbench';
import {Modal,FormModal,SearchSelect,Loading,Empty,Badge,useAction} from './ui';
import {DocumentPanel} from './knowledge';
import {ReviewSubmitModal} from './review-submit-modal';
import {RequirementFollowUp} from './requirement-follow-up';
import {canReviewCandidates,candidateItems} from './task-candidates';
import {packStageLabels,RequirementTaskActions,RequirementTaskRows,type Initialization,type PackStage} from './requirement-initialization';
import {DeleteRecordButton} from './delete-record-button';

type PackIdentity = {id:string; number:string; name:string};
type Pack = PackIdentity & {
 stages:Record<PackStage,{documents:Document[];runs:ProcessingTask[]}>;
 questions:Question[];
 children:Requirement[];
 reviews:Review[];
 review_versions:Version[];
 publish_jobs:{id:string;kind:string;status:string;version_id:string}[];
 initialization:Initialization|null;
 can_change:boolean;
};
type Workspace = {
 redirect_task_id?:string;
 requirement:Requirement;
 packs:Pack[];
};

const stages: {key:PackStage;label:string;items:{key:'tasks'|'documents'|'analysis'|'history';label:string}[]}[] = [
 {key:'clarification',label:packStageLabels.clarification,items:[{key:'tasks',label:'关联任务'},{key:'documents',label:'关联文档'},{key:'analysis',label:'澄清与关联'}]},
 {key:'specification',label:packStageLabels.specification,items:[{key:'tasks',label:'关联任务'},{key:'documents',label:'关联文档'},{key:'history',label:'审核与历史'}]},
 {key:'consolidation',label:packStageLabels.consolidation,items:[{key:'tasks',label:'关联任务'},{key:'documents',label:'关联文档'}]},
];
const oldTabs: Record<string,string> = {
 overview:'clarification-analysis',tasks:'clarification-tasks',documents:'clarification-documents',
 materials:'clarification-documents',analysis:'clarification-analysis',history:'specification-history',
};
export function RequirementEditor({requirement, close, done}: {
 requirement: Requirement; close: () => void; done?: (requirement: Requirement) => void;
}) {
 const {perform} = useAction();
 const [name, setName] = useState(requirement.title);
 const [number, setNumber] = useState(requirement.number);
 const [state, setState] = useState(requirement.state);
 const [busy, setBusy] = useState(false);
 const workflowLocked = ['specified', 'published'].includes(state);

 return <Modal title="编辑需求" close={close}>
  <form onSubmit={async event => {
   event.preventDefault();
   if (busy) return;
   setBusy(true);
   const saved = await perform(() => api<Requirement>(
    '/requirements/' + requirement.id + '?expected_revision=' + requirement.revision, 'PATCH', {
     number, title: name, description: requirement.description, state, acceptance: requirement.acceptance,
     tags: requirement.tags, source_version_id: requirement.source_version_id,
    }), '需求已保存');
   setBusy(false);
   if (saved) {close(); done?.(saved);}
  }}>
   <div className="form-fields">
    <label>需求编号<input aria-label="需求编号" maxLength={80} required value={number} onChange={e => setNumber(e.target.value)}/></label>
    <label>需求名称<input aria-label="需求名称" maxLength={300} required value={name} onChange={e => setName(e.target.value)}/></label>
    <label>需求整理状态{workflowLocked
     ? <input aria-label="需求整理状态" value={states[state]} readOnly/>
     : <SearchSelect aria-label="需求整理状态" value={state} onChange={e => setState(e.target.value)}>
        {['draft', 'clarifying', 'confirmed'].map(s => <option key={s} value={s}>{states[s]}</option>)}
       </SearchSelect>}
    </label>
   </div>
   <footer><button type="button" className="secondary" onClick={close}>取消</button><button className="primary" disabled={busy}>保存需求</button></footer>
  </form>
 </Modal>;
}

export function RequirementWorkspace({user,id,navigate,activeTab,activePackId,onTabChange:setTab,openTaskResult}: {
 user:User; id:string; navigate:(page:PageKey,id?:string,replace?:boolean)=>void;
 activeTab?:string; activePackId?:string; onTabChange:(tab:string,packId?:string)=>void;
 openTaskResult:(id:string,tab?:string)=>void;
}) {
 const {perform}=useAction();
 const [editing,setEditing]=useState(false);
 const [addingPack,setAddingPack]=useState(false);
 const [editingPack,setEditingPack]=useState<PackIdentity|null>(null);
 const [selectReview,setSelectReview]=useState(false);
 const [submit,setSubmit]=useState<{pack:Pack;version:Version}|null>(null);
 const [document,setDocument]=useState<{id:string;versionId:string}|null>(null);
 const {data,error,isLoading}=useQuery({
  queryKey:['workspace',id],queryFn:()=>api<Workspace>('/requirements/'+id+'/workspace'),refetchInterval:5000,
 });
 const {data:bases=[]}=useQuery({queryKey:['bases'],queryFn:()=>api<Base[]>('/knowledge-bases')});
 useEffect(()=>{if(data?.redirect_task_id)navigate('task',data.redirect_task_id,true);},[data?.redirect_task_id]);
 if(isLoading||data?.redirect_task_id)return <Loading/>;
 if(!data)return <p className="form-error">{error?.message||'需求不存在或无权限'}</p>;

 const requirement=data.requirement;
 const readOnly=user.role==='development_member'||requirement.can_edit===false;
 const requested=oldTabs[activeTab||'']||activeTab||'clarification-documents';
 const stage=stages.find(s=>requested.startsWith(s.key+'-'))||stages[0];
 const item=stage.items.find(item=>requested===stage.key+'-'+item.key
  &&(user.role!=='development_member'||item.key!=='history'))||stage.items[0];
 const tab=stage.key+'-'+item.key;
 const pack=data.packs.find(p=>p.id===activePackId)||data.packs[0];
 const content=pack?.stages[stage.key];
 const packLabel=pack?requirement.number+' / '+pack.number+' · '+pack.name:'';
 const scope=packLabel+' / '+stage.label;
 const detailRun=pack?.stages.clarification.runs.find(run=>canReviewCandidates(run)&&candidateItems(run,'requirements')
  .some((_,index)=>!((run.result.saved_requirement_indices||[]) as number[]).includes(index)));

 return <>
  <div className="page-heading workspace-heading">
   <div><h1>{requirement.title}</h1><p>{[requirement.number,...(requirement.tags['系统']||[])].join(' · ')}</p></div>
   <div className="button-group">
    {requirement.parent_id&&<button className="secondary" onClick={()=>navigate('requirement',requirement.parent_id!,true)}>返回所属需求</button>}
    {!readOnly&&<>
     <button className="secondary" onClick={()=>setEditing(true)}>编辑信息</button>
     <DeleteRecordButton kind="requirement" id={id} title={requirement.title} onDeleted={()=>navigate('requirements','business')}/>
     {pack&&<button className="primary" onClick={()=>setSelectReview(true)}>提交会签</button>}
    </>}
   </div>
  </div>
  {pack&&content?<section className="panel requirement-pack-layout">
   <aside className="requirement-pack-nav" aria-label="需求包导航">
    <div className="requirement-pack-nav-header"><strong>需求包</strong>
     {!readOnly&&<button type="button" className="text-button" onClick={()=>setAddingPack(true)}><Plus size={15}/>新增需求包</button>}
    </div>
    {data.packs.map(p=><div className="requirement-pack-branch" key={p.id}>
     <button type="button" className="requirement-pack-root" aria-expanded={p.id===pack.id} aria-controls={'pack-'+p.id}
      onClick={()=>setTab(tab,p.id)}>
      {p.id===pack.id?<ChevronDown size={15}/>:<ChevronRight size={15}/>}<Folder size={16}/>
      <strong>{p.number}</strong><span>{p.name}</span>
     </button>
     <div className="requirement-pack-children" id={'pack-'+p.id} hidden={p.id!==pack.id}>
      {!readOnly&&<div className="requirement-pack-actions">
       <button type="button" className="text-button" onClick={()=>setEditingPack(p)}>编辑名称</button>
       <DeleteRecordButton kind="requirement_pack" id={p.id} title={p.number+' · '+p.name}
        endpoint={`/requirements/${id}/packs/${p.id}`}
        notice="需求包将从列表移除，包编号及原有任务、文档、会签记录保留。未结束任务或会签需先处理。"
        onDeleted={()=>setTab('clarification-documents',data.packs.find(other=>other.id!==p.id)?.id||'')}/>
      </div>}
      {stages.map(s=><section className="requirement-stage-branch" key={s.key} aria-label={s.label}>
       <strong>{s.label}</strong>
       <div className="requirement-stage-leaves">
        {s.items.filter(entry=>user.role!=='development_member'||entry.key!=='history').map(entry=>{
          const target=s.key+'-'+entry.key;
          return <button type="button" key={entry.key} aria-current={target===tab?'page':undefined}
            onClick={()=>setTab(target,p.id)}>{entry.label}</button>;
        })}
       </div>
      </section>)}
     </div>
    </div>)}
   </aside>
   <section className="requirement-pack-main">
    <div className="toolbar requirement-pack-header">
     <nav className="requirement-pack-trail" aria-label="当前位置">{scope} / <strong>{item.label}</strong></nav>
     <span className="spacer"/>
     {!readOnly&&pack.initialization&&<RequirementTaskActions key={pack.id}
      id={id} plan={pack.initialization} scope={{id:pack.id,stage:stage.key,label:packLabel,canChange:pack.can_change}}
      bases={bases} navigate={navigate}/>}
    </div>
    <div className="toolbar"><h2>{item.label}</h2></div>
    {item.key==='tasks'&&<>
     <RequirementTaskRows runs={content.runs} navigate={navigate} openResult={readOnly?undefined:openTaskResult} readOnly={readOnly}/>
     {stage.key==='consolidation'&&pack.publish_jobs.map(job=><div className="version-row" key={job.id}>
      <div><strong>{job.kind==='publish'?'正式发布与索引':'重建索引'}</strong><small className="block muted">{states[job.status]||job.status}</small></div>
      {content.documents.flatMap(doc=>doc.versions).some(v=>v.id===job.version_id)&&
       <button className="secondary" onClick={()=>{
        const doc=content.documents.find(d=>d.versions.some(v=>v.id===job.version_id));
        if(doc)setDocument({id:doc.id,versionId:job.version_id});
       }}>查看版本</button>}
     </div>)}
     {!content.runs.length&&(stage.key!=='consolidation'||!pack.publish_jobs.length)&&<Empty text="本阶段暂无任务"/>}
    </>}
    {item.key==='documents'&&<>
     <p className="notice">关联位置 · {scope}</p>
     {content.documents.map(doc=><section className="workspace-document" key={doc.id}>
      <div>
       <h3><FileText size={16} aria-hidden="true"/> {doc.title}</h3>
       {doc.versions.map(version=><div className="version-row" key={version.id}>
        <span>{version.label} · {versionStage(version)}</span>
        <button className="text-button" onClick={()=>setDocument({id:doc.id,versionId:version.id})}>查看版本</button>
        {!readOnly&&stage.key==='specification'&&doc.kind==='specification'&&doc.owner_id===user.id&&
         version.parse_status==='ready'&&doc.requirement_id===id&&
         <button className="text-button" onClick={()=>navigate('editor','version~'+version.id)}>编辑文档</button>}
       </div>)}
      </div>
     </section>)}
     {!content.documents.length&&<Empty text="本阶段暂无关联文档"
      detail={readOnly?'关联后的文档会显示在这里。':'可在「发起任务」中选用已有文件或上传新文件。'}/>}
    </>}
    {item.key==='analysis'&&<>
     <RequirementFollowUp key={pack.id} id={id} packId={pack.id} questions={pack.questions} readOnly={readOnly}
      viewTasks={()=>setTab('clarification-tasks',pack.id)} openRequirement={otherId=>navigate('requirement',otherId)}/>
     <div className="panel-heading"><h3>结构化明细（{pack.children.length}）</h3>
      {!readOnly&&detailRun&&<button className="secondary" onClick={()=>openTaskResult(detailRun.id,'requirements')}>查看待确认明细</button>}
     </div>
     {pack.children.map(child=><button className="workspace-row" key={child.id} onClick={()=>navigate('requirement',child.id)}>
      <strong>{child.number} · {child.title}</strong><span>{child.description}</span><Badge state={child.state}/>
     </button>)}
    </>}
    {item.key==='history'&&<>
     {pack.reviews.map(review=><button className="workspace-row" key={review.id} onClick={()=>navigate('reviews',review.id)}>
      <strong>{states[review.status]||review.status}</strong><span>{review.note||'查看审核意见与会签进度'}</span><small>{date(review.created_at)}</small>
     </button>)}
     {!pack.reviews.length&&<Empty text="本包暂无会签记录"/>}
    </>}
   </section>
  </section>:requirement.kind==='detail'?<section className="panel form-fields"><p>{requirement.description||'尚未填写结构化明细说明。'}</p>
   {requirement.acceptance&&<p>{requirement.acceptance}</p>}</section>:<section className="panel">
    {!readOnly&&<div className="toolbar"><button type="button" className="primary" onClick={()=>setAddingPack(true)}><Plus size={15}/>新增需求包</button></div>}
    <Empty text="暂无需求包" detail="新增需求包后可在包内关联文档并发起任务。"/>
   </section>}
  {editing&&<RequirementEditor requirement={requirement} close={()=>setEditing(false)}/>}
  {addingPack&&<FormModal title="新增需求包" fields={[{key:'name',label:'需求包名称',required:true}]}
   close={()=>setAddingPack(false)} onSubmit={async values=>{
    const created=await perform(()=>api<PackIdentity>('/requirements/'+id+'/packs','POST',values),'需求包已新增');
    if(created)setTab('clarification-documents',created.id);
    return created;
   }}/>}
  {editingPack&&<FormModal title="编辑需求包名称" initial={{name:editingPack.name}}
   fields={[{key:'name',label:'需求包名称',required:true}]} close={()=>setEditingPack(null)}
   onSubmit={values=>perform(()=>api(`/requirements/${id}/packs/${editingPack.id}`,'PATCH',values),'需求包名称已保存')}/>}
  {selectReview&&<PackReviewSelection packs={data.packs} close={()=>setSelectReview(false)}
   next={(pack,version)=>{setSelectReview(false);setSubmit({pack,version});}}/>}
  {submit&&<ReviewSubmitModal versions={[submit.version]} expectedPackId={submit.pack.id}
   unresolvedCount={submit.pack.questions.filter(q=>['open','answered'].includes(q.status)).length}
   close={()=>setSubmit(null)} complete={()=>setTab('specification-history',submit.pack.id)}/>}
  {document&&<DocumentPanel user={user} documentId={document.id} initialVersionId={document.versionId} close={()=>setDocument(null)}/>}
 </>;
}

function PackReviewSelection({packs,close,next}: {packs:Pack[];close:()=>void;next:(pack:Pack,version:Version)=>void}) {
 const [packId,setPackId]=useState('');
 const [versionId,setVersionId]=useState('');
 const pack=packs.find(p=>p.id===packId);
 const version=pack?.review_versions.find(v=>v.id===versionId);
 return <Modal title="提交会签" close={close}>
  <form onSubmit={event=>{event.preventDefault();if(pack&&version)next(pack,version);}}>
   <div className="form-fields">
    <label>需求包<SearchSelect value={packId} onChange={event=>{setPackId(event.target.value);setVersionId('');}} required>
     <option value="">请选择需求包</option>
     {packs.map(item=><option key={item.id} value={item.id}>{item.number} · {item.name}</option>)}
    </SearchSelect></label>
    <label>软需版本<SearchSelect value={versionId} onChange={event=>setVersionId(event.target.value)} disabled={!pack} required>
     <option value="">{pack?'请选择软需版本':'请先选择需求包'}</option>
     {pack?.review_versions.map(v=><option key={v.id} value={v.id}>{v.filename} · {v.label}</option>)}
    </SearchSelect></label>
    {pack&&!pack.review_versions.length&&<p className="muted">当前需求包暂无可提交会签的软需草稿。</p>}
   </div>
   <footer><button type="button" className="secondary" onClick={close}>取消</button>
    <button className="primary" disabled={!version}>下一步</button></footer>
  </form>
 </Modal>;
}

