'use client';
import {requirementLabel} from '../lib/business-identity';
import {useState,useEffect} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Plus,Download,History,Pencil,Check,X} from 'lucide-react';
import {api,states} from '../lib/api';
import type {User,Task,Requirement} from '../lib/types';
import type {PageKey} from './workbench';
import {Tabs,SearchBox,Loading,Empty,FormModal,Modal,JsonView,Badge,useAction,FormField,SearchSelect} from './ui';
import {Chart} from './dashboard';
import {DeleteRecordButton} from './delete-record-button';
import {ClarificationImport} from './clarification-import';

const fallback=['需求编号','需求名称'];
const PAGE_SIZE=15;
const statuses=['pending','in_progress','completed','not_needed'].map(value=>({value,label:states[value]}));

function EditableCell({task,column,index,editable}:{task:Task;column:string;index:number;editable:boolean}) {
  const [editing,setEditing]=useState(false);const [baseline,setBaseline]=useState<Task|null>(null);
  const [value,setValue]=useState('');
  const [busy,setBusy]=useState(false);
  const {perform}=useAction();
  async function save(){if(!editable)return;const original=baseline||task;setBusy(true);const result=await perform(()=>api('/clarification/tasks/'+task.id,'PATCH',{fields:{...original.fields,[column]:value},status:original.status,requirement_id:original.requirement_id,expected_revision:original.revision}),'字段已更新');setBusy(false);if(result)setEditing(false);}
  return <td className={(column==='需求名称'?'ledger-title ':'')+(index<2?'ledger-frozen':'')} style={index<2?{left:44+index*170}:undefined}>{editing?<div className="ledger-cell-editor"><textarea autoFocus aria-label={'修改'+column} value={value} onChange={event=>setValue(event.target.value)} onKeyDown={event=>{if(event.key==='Escape')setEditing(false);if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();void save();}}}/><div><button className="icon-button" title="保存字段" disabled={busy} onClick={()=>void save()}><Check size={14}/></button><button className="icon-button" title="取消修改" onClick={()=>setEditing(false)}><X size={14}/></button></div></div>:<button className="ledger-cell-value" title={editable?'双击修改：'+column:'公共台账 · 只读'} onDoubleClick={()=>{if(!editable)return;setBaseline(task);setValue(String(task.fields[column]??''));setEditing(true);}}>{String(task.fields[column]??'—')}</button>}</td>;
}

export function ClarificationPage({user,navigate,activeTab='tasks',onTabChange:setTab}:{user:User;navigate:(key:PageKey,id?:string)=>void;activeTab?:string;onTabChange:(tab:string)=>void}) {
  const {perform}=useAction();
  const [view,setView]=useState('all');const tab=activeTab;const [q,setQ]=useState('');const [status,setStatus]=useState('');
  const [form,setForm]=useState<Task|null|'new'>(null);const [formColumns,setFormColumns]=useState<string[]>([]);
  const [linkTask,setLinkTask]=useState<Task|null>(null);const [linkRequirement,setLinkRequirement]=useState('');const [matches,setMatches]=useState<{id:string;number:string;title:string}[]>([]);const [history,setHistory]=useState('');const [selected,setSelected]=useState<string[]>([]);const [page,setPage]=useState(0);const [sort,setSort]=useState('需求编号');const [ascending,setAscending]=useState(true);
  const {data:tasks=[],isLoading}=useQuery({queryKey:['tasks'],queryFn:()=>api<Task[]>('/clarification/tasks'),refetchInterval:5000});
  const {data:layout}=useQuery({queryKey:['ledger-columns'],queryFn:()=>api<{columns:string[];own_columns?:string[]}>('/clarification/columns'),refetchInterval:5000});
  const columns=Array.from(new Set([...(layout?.columns||Object.keys(tasks[0]?.fields||{})),...tasks.flatMap(task=>Object.keys(task.fields))]));
  const fields=columns.length?columns:fallback;
  const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements'),select:rows=>rows.filter(r=>r.can_edit!==false)});
  const {data:changes}=useQuery({queryKey:['task-history',history],queryFn:()=>api<unknown>('/clarification/tasks/'+history+'/history'),enabled:!!history});
  const visible=tasks.filter(task=>(!status||task.status===status)&&(!q||JSON.stringify(task.fields).toLowerCase().includes(q.toLowerCase()))).sort((a,b)=>String(a.fields[sort]??'').localeCompare(String(b.fields[sort]??''),'zh-CN')*(ascending?1:-1));
  const maxPage=Math.max(0,Math.ceil(visible.length/PAGE_SIZE)-1);const currentPage=Math.min(page,maxPage);const displayed=visible.slice(currentPage*PAGE_SIZE,(currentPage+1)*PAGE_SIZE);
  const counts=tasks.reduce<Record<string,number>>((result,task)=>({...result,[states[task.status]||task.status]:(result[states[task.status]||task.status]||0)+1}),{});
  const groups:Record<string,string[]>={common:['需求编号','需求名称','申请部门','业务对接人','业务紧急程度','软需负责人','软需进展'],clarification:['需求编号','需求名称','澄清周','澄清时间','澄清结果','会议结论','备注'],delivery:['需求编号','需求名称','实施对接人','软需负责人','软需进展','软需完成时间','工作量']};
  const displayFields=view==='all'?fields:fields.filter(column=>(groups[view]||[]).includes(column));
  const canEdit=(task:Task)=>task.can_edit??(!task.owner_id||task.owner_id===user.id);
  const editableTasks=tasks.filter(canEdit);const editableDisplayed=displayed.filter(canEdit);
  const editableFields=formColumns.length?formColumns:fields;
  useEffect(()=>{setSelected(ids=>{const kept=ids.filter(id=>tasks.some(task=>task.id===id&&canEdit(task)));return kept.length===ids.length?ids:kept;});},[tasks]);
  const qaFields=fields.slice(0,Math.max(2,fields.indexOf('备注')+1));
  const displayedFormFields=form==='new'&&user.role==='qa_member'?qaFields:editableFields;
  const taskFields:FormField[]=displayedFormFields.map((column,index)=>({
    key:'column:'+index,label:column,type:'textarea',
    required:user.role!=='qa_member'&&(column==='需求编号'||column==='需求名称'),
    hint:form==='new'&&column==='需求编号'?'保存时按需求编号自动关联已有需求。':undefined,
  }));
  if(user.role!=='qa_member'||form!=='new')taskFields.push({
    key:'_status',label:'规范化处理状态',type:'select',options:statuses,required:true,
  });
  if(form&&form!=='new')taskFields.push({
    key:'_requirement_id',label:'关联需求',type:'select',options:requirements.map(r=>({value:r.id,label:requirementLabel(r)})),
  });
  function afterImport(){
    setPage(0);setSelected([]);setQ('');setStatus('');setView('all');setSort('需求编号');setAscending(true);
  }
  return <><div className="page-heading"><div><span className="eyebrow">CLARIFICATION MANAGEMENT</span><h1>需求澄清计划</h1><p>公共台账，所有登录用户可查看、导出和查看修改记录；本人登记的计划可编辑。</p></div><div className="button-group"><button className="primary" onClick={()=>{setFormColumns(fields);setForm('new');}}><Plus size={17}/>新增计划</button></div></div>
    <section className="panel"><Tabs items={[{key:'tasks',label:'澄清计划台账'},{key:'stats',label:'澄清进度统计'}]} value={tab} onChange={setTab}/>
    {tab==='tasks'&&<><div className="toolbar"><SearchBox value={q} onChange={value=>{setQ(value);setPage(0);}} placeholder="搜索表格中的全部字段"/><SearchSelect aria-label="筛选处理状态" value={status} onChange={event=>{setStatus(event.target.value);setPage(0);}}><option value="">全部状态</option>{statuses.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</SearchSelect><SearchSelect aria-label="字段视图" value={view} onChange={event=>setView(event.target.value)}><option value="all">全部原始字段</option><option value="common">常用信息</option><option value="clarification">澄清信息</option><option value="delivery">交付进展</option></SearchSelect><span className="muted small">{fields.length} 个公共字段 · 本人计划可双击编辑</span><span className="spacer"/><ClarificationImport onImported={afterImport}/><a className="secondary" href="/api/clarification/export"><Download size={15}/>Excel 导出</a></div>
    {selected.length>0&&<div className="bulk-toolbar"><span>已选 {selected.length} 条</span><SearchSelect aria-label="批量设置状态" value="" onChange={event=>{const value=event.target.value;if(value)void perform(()=>api('/clarification/batch','POST',{items:selected.map(id=>{const task=tasks.find(task=>task.id===id)!;return {id,expected_revision:task.revision,status:value};})}),'批量更新完成');}}><option value="">批量设置状态</option>{statuses.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</SearchSelect><button className="text-button" onClick={()=>setSelected([])}>取消选择</button></div>}
    {isLoading?<Loading/>:visible.length?<div className="table-wrap ledger-table"><table style={{minWidth:displayFields.length*170+220}}><thead><tr><th><input type="checkbox" aria-label="选择当前页" disabled={!editableDisplayed.length} checked={editableDisplayed.length>0&&editableDisplayed.every(task=>selected.includes(task.id))} onChange={event=>setSelected(event.target.checked?Array.from(new Set([...selected,...editableDisplayed.map(task=>task.id)])):selected.filter(id=>!editableDisplayed.some(task=>task.id===id)))}/></th>{displayFields.map((column,index)=><th className={index<2?'ledger-frozen':''} style={index<2?{left:44+index*170}:undefined} key={column}><button onClick={()=>{setAscending(sort===column?!ascending:true);setSort(column);}}>{column}{sort===column?(ascending?' ↑':' ↓'):''}</button></th>)}<th>处理状态</th><th>登记人</th><th>操作</th></tr></thead><tbody>{displayed.map(task=><tr key={task.id}><td><input type="checkbox" aria-label={'选择台账 '+task.fields['需求编号']} disabled={!canEdit(task)} checked={canEdit(task)&&selected.includes(task.id)} onChange={event=>setSelected(event.target.checked?[...selected,task.id]:selected.filter(id=>id!==task.id))}/></td>{displayFields.map((column,index)=><EditableCell editable={canEdit(task)} index={index} key={column} task={task} column={column}/>)}<td><Badge state={task.status}/></td><td>{task.owner_name||'登记人'}{!canEdit(task)&&<small className="block muted">公共可见 · 只读</small>}</td><td><div className="button-group">{canEdit(task)&&<button className="icon-button" title="编辑全部字段" onClick={()=>{setFormColumns(Array.from(new Set([...(layout?.own_columns||Object.keys(task.fields)),...Object.keys(task.fields)])));setForm(task);}}><Pencil size={15}/></button>}{canEdit(task)&&!task.requirement_id&&<button className="text-button" onClick={async()=>{setLinkTask(task);setLinkRequirement(task.requirement_id||'');setMatches(await api('/clarification/tasks/'+task.id+'/requirement-candidates'));}}>关联需求</button>}<button className="text-button" disabled={!task.requirement_id||task.can_open_requirement===false} onClick={()=>navigate('requirement',task.requirement_id!)}>需求详情</button>{(task.can_delete??(canEdit(task)||user.role==='super_admin'))&&<DeleteRecordButton kind="clarification_task" id={task.id} title={String(task.fields['需求名称']||task.fields['需求编号']||'澄清计划')} onDeleted={()=>setSelected(ids=>ids.filter(id=>id!==task.id))}/>}<button className="icon-button" title="修改记录" onClick={()=>setHistory(task.id)}><History size={15}/></button></div></td></tr>)}</tbody></table></div>:<Empty text="暂无澄清计划" detail="导入 Excel 后保留表头顺序和全部字段。"/>}<div className="pagination"><span>共 {visible.length} 条 · 第 {currentPage+1} 页</span><button className="secondary" disabled={!currentPage} onClick={()=>setPage(currentPage-1)}>上一页</button><button className="secondary" disabled={currentPage>=maxPage} onClick={()=>setPage(currentPage+1)}>下一页</button></div></>}
    {tab==='stats'&&<div className="charts-grid embedded-charts"><Chart title="澄清任务状态" values={counts}/></div>}</section>
    {form&&<FormModal title={form==='new'?'新增澄清计划':'编辑台账全部字段'} fields={taskFields} initial={{...Object.fromEntries(displayedFormFields.map((column,index)=>['column:'+index,form==='new'?'':form.fields[column]])),_status:form==='new'?'pending':form.status,_requirement_id:form==='new'?'':form.requirement_id}} close={()=>setForm(null)} onSubmit={values=>perform(()=>api(form==='new'?'/clarification/tasks':'/clarification/tasks/'+form.id,form==='new'?'POST':'PATCH',{fields:Object.fromEntries(displayedFormFields.map((column,index)=>{const old=form==='new'?undefined:form.fields[column];const value=values['column:'+index];return [column,String(old??'')===value&&form!=='new'?old:value];})),status:values._status||'pending',requirement_id:values._requirement_id||null,expected_revision:form==='new'?null:form.revision}))}/>} {linkTask&&<Modal title="台账关联业务需求" close={()=>setLinkTask(null)}><div className="form-fields"><p>同一需求可关联多条台账记录，原表各行分别保留。请核对编号、系统与项目后选择。</p>{matches.length>0&&<p className="notice">编号匹配：{matches.map(r=><button className="text-button" key={r.id} onClick={()=>setLinkRequirement(r.id)}>{r.number} {r.title}</button>)}</p>}<label>业务需求<SearchSelect value={linkRequirement} onChange={e=>setLinkRequirement(e.target.value)}><option value="">暂不关联</option>{requirements.filter(r=>!r.kind||r.kind==='business').map(r=><option key={r.id} value={r.id}>{requirementLabel(r)}</option>)}</SearchSelect></label><button className="primary" onClick={async()=>{const done=await perform(()=>api('/clarification/tasks/'+linkTask.id+'/requirement','PUT',{requirement_id:linkRequirement||null,expected_revision:linkTask.revision}),'台账关联已更新');if(done)setLinkTask(null);}}>确认关联</button><button className="secondary" onClick={()=>navigate('requirements','new')}>登记新的业务需求</button></div></Modal>} {history&&<Modal title="台账修改历史" close={()=>setHistory('')}><JsonView value={changes}/></Modal>}</>;
}
