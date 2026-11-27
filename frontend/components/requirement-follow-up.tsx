'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../lib/api';
import type {Question,Relation,Requirement} from '../lib/types';
import {Badge,Empty,JsonView,Loading,Tabs,useAction} from './ui';
import {DeleteRecordButton} from './delete-record-button';
import {RequirementQuestionForm} from './requirement-candidates';

export function RequirementFollowUp({id,packId,questions,readOnly,viewTasks,openRequirement}:{id:string;packId?:string;questions:Question[];readOnly:boolean;viewTasks:()=>void;openRequirement:(id:string)=>void}){
 const [tab,setTab]=useState('questions');
 const [all,setAll]=useState(false);
 const [question,setQuestion]=useState<Question|'new'|null>(null);
 const pending=questions.filter(q=>q.status==='open'||q.status==='answered');
 const shown=all?questions:pending;
 return <section className="form-fields">
  <Tabs items={[{key:'questions',label:`澄清问题（待处理 ${pending.length}）`},{key:'relations',label:'需求关联'}]} value={tab} onChange={setTab}/>
  {tab==='questions'?<>
   <div className="toolbar">
    <div className="button-group" aria-label="澄清问题筛选">
     <button type="button" className={all?'secondary':'primary'} aria-pressed={!all} onClick={()=>setAll(false)}>待处理</button>
     <button type="button" className={all?'primary':'secondary'} aria-pressed={all} onClick={()=>setAll(true)}>全部问题（{questions.length}）</button>
    </div><span className="spacer"/>
    {!readOnly&&<button className="secondary" onClick={()=>setQuestion('new')}>新增澄清问题</button>}
   </div>
   {shown.map(q=><article className="question-card" key={q.id}>
    <div className="task-candidate-heading"><h3>{q.description}</h3><Badge state={q.status}/></div>
    {q.reason&&<p>{q.reason}</p>}{q.feedback&&<p>业务反馈：{q.feedback}</p>}{q.conclusion&&<p>结论：{q.conclusion}</p>}
    {q.evidence&&Object.keys(q.evidence).length>0&&<details><summary>来源依据</summary><JsonView value={q.evidence}/></details>}
    {!readOnly&&<div className="button-group"><button className="text-button" onClick={()=>setQuestion(q)}>反馈与确认结论</button>
     <DeleteRecordButton kind="question" id={q.id} title={q.description}/></div>}
   </article>)}
   {!shown.length&&<Empty text={all?'暂无已保存的澄清问题':'暂无待处理澄清问题'} detail={questions.length?'已处理的问题可在「全部问题」查看。':'手动新增问题，或从任务结果保存澄清问题。'}/>}
  </>:<SavedRelations id={id} packId={packId} readOnly={readOnly} openRequirement={openRequirement}/>}
  {!readOnly&&<button type="button" className="text-button" onClick={viewTasks}>前往关联任务查看候选结果</button>}
  {question&&<RequirementQuestionForm requirementId={id} packId={packId} question={question==='new'?undefined:question} close={()=>setQuestion(null)}/>}
 </section>;
}

function SavedRelations({id,packId,readOnly,openRequirement}:{id:string;packId?:string;readOnly:boolean;openRequirement:(id:string)=>void}){
 const {perform}=useAction();
 const [busy,setBusy]=useState<string|null>(null);
 const {data:relations=[],error,isLoading}=useQuery({queryKey:['relations',id,packId],queryFn:()=>api<Relation[]>(
  packId?`/relations?requirement_id=${id}&pack_id=${packId}`:'/relations')});
 const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});
 const relevant=relations.filter(relation=>relation.source_id===id||relation.target_id===id);
 const ordered=[...relevant].sort((a,b)=>Number(b.status==='candidate')-Number(a.status==='candidate'));
 async function decide(relationId:string,status:string){
  setBusy(relationId);
  try{await perform(()=>api(`/relations/${relationId}`,'PATCH',{status}),'关联状态已更新');}finally{setBusy(null);}
 }
 if(isLoading)return <Loading/>;
 if(error)return <p className="form-error">{error.message}</p>;
 if(!ordered.length)return <Empty text="暂无已保存的需求关联" detail="可从变更影响分析的结果中选择目标需求并保存关联候选。"/>;
 return <>{ordered.map(relation=>{
  const outward=relation.source_id===id;
  const otherId=outward?relation.target_id:relation.source_id;
  const other=requirements.find(r=>r.id===otherId);
  const evidence=relation.evidence as {description?:string;candidate?:{description?:string}};
  const description=evidence.description||evidence.candidate?.description;
  return <article className="relation-card" key={relation.id}>
   <div className="task-candidate-heading"><strong>{relation.kind}</strong><Badge state={relation.status}/></div>
   <p>{outward?'影响目标':'关联来源'}　{other?<button type="button" className="text-button" onClick={()=>openRequirement(other.id)}>{other.number} {other.title}</button>:'关联需求'}</p>
   {description&&<p>{description}</p>}
   {!!Object.keys(relation.evidence).length&&<details><summary>来源依据</summary><JsonView value={relation.evidence}/></details>}
   {!readOnly&&<div className="button-group">{relation.status==='candidate'&&<>
    <button className="primary" disabled={busy!==null} onClick={()=>void decide(relation.id,'confirmed')}>确认关联</button>
    <button className="secondary" disabled={busy!==null} onClick={()=>void decide(relation.id,'rejected')}>拒绝关联</button>
   </>}<DeleteRecordButton kind="relation" id={relation.id} title={relation.kind}/></div>}
  </article>;
 })}</>;
}
