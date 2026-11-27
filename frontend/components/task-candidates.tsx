'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../lib/api';
import {requirementLabel} from '../lib/business-identity';
import type {Citation,Json,Requirement,Run} from '../lib/types';
import {Empty,JsonView,SearchBox,SearchSelect,Tabs,useAction} from './ui';

const sections={requirements:['analysis','items','结构化需求'],questions:['clarification','questions','澄清问题'],relations:['impact','relations','影响候选']} as const;
export type CandidateTab=keyof typeof sections;
type Item=Record<string,Json>;
const displayNames:Record<string,string>={tags:'需求标签',roles:'角色',systems:'涉及系统',system:'系统',
 current_behavior:'当前行为',target_behavior:'目标行为',acceptance:'验收标准',open_questions:'待确认事项',
 reason:'提出原因',target:'澄清对象',category:'分类',kind:'关系类型',function:'功能',flow:'流程',
 field:'字段',interface:'接口',evidence_kind:'证据类型',blocking:'阻塞生成'};
const batchSize=15;

export function candidateItems(run:Run,tab:CandidateTab):Item[]{
 const [group,field]=sections[tab];
 const items=(run.result[group] as Record<string,Json>|undefined)?.[field];
 return Array.isArray(items)?items as Item[]:[];
}

export function canReviewCandidates(run:Run){
 return ['completed','awaiting_confirmation'].includes(run.status)||Boolean(run.inputs._initialization);
}

const candidateTabs=Object.keys(sections) as CandidateTab[];
export function hasCandidates(run:Run){
 return candidateTabs.some(tab=>candidateItems(run,tab).length>0);
}

function pretty(value:Json):string{
 if(value===null)return '';
 if(Array.isArray(value))return value.map(pretty).join('、');
 if(typeof value==='object')return Object.entries(value).map(([name,entry])=>name+'：'+pretty(entry)).join('；');
 if(typeof value==='boolean')return value?'是':'否';
 return String(value);
}

export function TaskCandidates({run,requirementId,initialTab}:{run:Run;requirementId?:string|null;initialTab?:CandidateTab}){
 const tabs=candidateTabs.filter(tab=>candidateItems(run,tab).length);
 const preferred=initialTab||(run.workflow==='clarification'?'questions':run.workflow==='impact'?'relations':'requirements');
 const [active,setActive]=useState<CandidateTab>(preferred);
 const current=tabs.includes(active)?active:tabs[0];
 if(!current)return null;
 return <section className="form-fields task-candidates">
  <Tabs items={tabs.map(tab=>({key:tab,label:`${sections[tab][2]}（${candidateItems(run,tab).length}）`}))}
   value={current} onChange={tab=>setActive(tab as CandidateTab)}/>
  <CandidateList key={current+':'+requirementId} run={run} tab={current} requirementId={requirementId}/>
 </section>;
}

function CandidateList({run,tab,requirementId}:{run:Run;tab:CandidateTab;requirementId?:string|null}){
 const {perform}=useAction();
 const [selected,setSelected]=useState<number[]>([]);
 const [target,setTarget]=useState('');
 const [filter,setFilter]=useState('all');
 const [search,setSearch]=useState('');
 const [limit,setLimit]=useState(batchSize);
 const [saving,setSaving]=useState(false);
 const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements'),enabled:tab==='relations'&&!!requirementId});
 const savedIndices=(run.result[tab==='requirements'?'saved_requirement_indices':'saved_question_indices']||[]) as number[];
 const savedRelations=(run.result.saved_relation_keys||[]) as string[];
 const isSaved=(index:number)=>tab==='relations'?(target?savedRelations.includes(`${index}:${target}`):savedRelations.some(key=>key.startsWith(`${index}:`))):savedIndices.includes(index);
 const ready=canReviewCandidates(run)&&!!requirementId;
 const items=candidateItems(run,tab);
 const rows=items.map((item,index)=>({item,index,saved:isSaved(index)})).filter(({item,saved})=>{
  if(filter==='saved'&&!saved||filter==='pending'&&saved||filter==='blocking'&&item.blocking!==true)return false;
  return `${item.title??''} ${item.description??''} ${item.kind??''} ${item.category??''}`.toLowerCase().includes(search.trim().toLowerCase());
 });
 const pendingSelection=selected.filter(index=>tab==='relations'&&!target||!isSaved(index));
 const visible=rows.slice(0,limit);
 const selectable=visible.filter(row=>!row.saved||tab==='relations'&&!target).map(row=>row.index);
 const allSelected=selectable.length>0&&selectable.every(index=>pendingSelection.includes(index));
 const action=tab==='requirements'?'确认所选结构化需求':tab==='questions'?'保存所选澄清问题':'保存所选关联候选';
 async function save(){
  const path={requirements:'save-requirements',questions:'save-questions',relations:'save-relations'}[tab];
  setSaving(true);
  try{
   const result=await perform(()=>api(`/agent-runs/${run.id}/${path}`,'POST',{
    selected_indices:pendingSelection,confirm:tab==='requirements',target_id:target,
   }),tab==='requirements'?'明细已保存，见需求概览':tab==='questions'?'问题已保存，见需求的「澄清与关联」':'关联候选已保存，见需求的「澄清与关联」');
   if(result)setSelected([]);
  }finally{setSaving(false);}
 }
 return <>
  {tab==='questions'&&<p className="muted">保存后可在「澄清与关联」记录反馈并确认结论。</p>}
  {tab==='relations'&&requirementId&&<label>关联目标需求<SearchSelect aria-label="关联目标需求" value={target} disabled={saving}
   onChange={event=>{setTarget(event.target.value);setSelected([]);}}>
    <option value="">搜索并选择目标需求</option>{requirements.filter(r=>r.can_edit!==false&&(!r.kind||r.kind==='business')&&r.id!==requirementId).map(r=><option key={r.id} value={r.id}>{requirementLabel(r)}</option>)}
   </SearchSelect></label>}
  {!requirementId&&<p className="notice">关联业务需求后即可保存候选。</p>}
  <div className="toolbar"><SearchBox value={search} onChange={value=>{setSearch(value);setLimit(batchSize);}} placeholder="搜索候选内容"/>
   <SearchSelect aria-label="候选状态筛选" value={filter} onChange={event=>{setFilter(event.target.value);setLimit(batchSize);}}>
    <option value="all">全部候选</option><option value="pending">待保存</option><option value="saved">已保存</option>
    {tab==='questions'&&<option value="blocking">阻塞项</option>}
   </SearchSelect><span className="muted">{rows.length} 条结果</span>
  </div>
  {ready&&<div className="toolbar candidate-actions">
   <button type="button" className="secondary" disabled={saving||!selectable.length}
    onClick={()=>setSelected(current=>allSelected?current.filter(i=>!selectable.includes(i)):[...new Set([...current,...selectable])])}>
    {allSelected?'取消选中当前列表':'选中当前列表'}</button>
   <span role="status" className="muted">已选 {pendingSelection.length} 条</span><span className="spacer"/>
   <button type="button" className="primary" disabled={saving||!pendingSelection.length||tab==='relations'&&!target} onClick={()=>void save()}>
    {saving?'保存中…':action}</button>
  </div>}
  {visible.length?<ul className="task-candidate-list">{visible.map(({item,index,saved})=><CandidateRow key={index} item={item} index={index}
   saved={saved} checked={pendingSelection.includes(index)} disabled={!ready||saving||saved&&(tab!=='relations'||!!target)}
   citation={run.citations?.find(source=>source.citation_id===item.source_citation_id)}
   onChange={checked=>setSelected(current=>checked?[...current,index]:current.filter(i=>i!==index))}/>)}</ul>:
   <Empty text="暂无匹配的候选" detail="可调整搜索内容或状态筛选。"/>}
  {limit<rows.length&&<button type="button" className="secondary" onClick={()=>setLimit(limit+batchSize)}>展开更多候选（剩余 {rows.length-limit} 条）</button>}
  {!!run.citations?.length&&<details><summary>本次分析的来源与版本（{run.citations.length} 条）</summary>
   <ul>{run.citations.map((source,index)=><li key={index}>{[source.title,source.version,source.locator].filter(Boolean).join(' · ')||source.citation_id}</li>)}</ul>
  </details>}
 </>;
}

function CandidateRow({item,index,saved,checked,disabled,citation,onChange}:{item:Item;index:number;saved:boolean;checked:boolean;
 disabled:boolean;citation?:Citation;onChange:(value:boolean)=>void}){
 const description=String(item.description||'');
 const title=String(item.title||description||item.kind||`候选 ${index+1}`);
 const fields=Object.entries(item).filter(([key,value])=>Object.hasOwn(displayNames,key)&&pretty(value));
 const source=citation&&[citation.title,citation.version,citation.locator].filter(Boolean).join(' · ');
 return <li className="task-candidate-row">
  <input type="checkbox" aria-label={`选择候选 ${index+1} ${title}`} checked={checked} disabled={disabled} onChange={event=>onChange(event.target.checked)}/>
  <div>
   <div className="task-candidate-heading"><strong className="task-candidate-title">{title}</strong><span className={'badge '+(saved?'confirmed':'pending')}>{saved?'已保存':'待保存'}</span>
    {item.blocking===true&&<span className="badge failed">阻塞项</span>}
   </div>
   {item.title&&description&&<p className="task-candidate-summary">{description}</p>}
   <details><summary>查看依据与明细</summary>
    {description&&<p>{description}</p>}
    {(source||item.source_citation_id)&&<p>来源 {source||String(item.source_citation_id)}</p>}
    {fields.length>0&&<dl className="candidate-fields">{fields.map(([key,value])=><div key={key}><dt>{displayNames[key]}</dt><dd>{pretty(value)}</dd></div>)}</dl>}
    <details><summary>原始结果</summary><JsonView value={item}/></details>
   </details>
  </div>
 </li>;
}
