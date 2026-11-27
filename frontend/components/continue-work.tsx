'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api,date} from '../lib/api';
import type {WorkItem} from '../lib/journey';
import type {PageKey} from './workbench';
import {Tabs,Loading,Empty} from './ui';
export function ContinueWork({navigate}:{navigate:(page:PageKey,id?:string)=>void}){
 const [scope,setScope]=useState('all');const {data:items=[],isLoading,error}=useQuery({queryKey:['work-items'],queryFn:()=>api<WorkItem[]>('/work-items'),refetchInterval:5000});
 const visible=items.filter(item=>scope==='all'||(scope==='editing'?['outline','editing','document_ready','generating','generation_failed','analysis_ready','clarification'].includes(item.stage):['version_confirmed','review_todo','reviewing','returned','publishing','publish_failed'].includes(item.stage)));
 return <section className="panel continue-work"><div className="panel-heading"><div><h2>继续处理</h2><p className="muted small">待确认、未完成编辑、会签与发布任务统一在这里恢复。</p></div><span className="badge">{items.length} 项</span></div><Tabs items={[{key:'all',label:'全部待办'},{key:'editing',label:'生成、编辑与澄清'},{key:'review',label:'审核与发布'}]} value={scope} onChange={setScope}/>{isLoading?<Loading/>:error?<p className="form-error">{error.message}</p>:visible.length?<div className="work-item-list">{visible.map(item=><button className="workspace-row" key={item.id} onClick={()=>navigate(item.destination.page as PageKey,item.destination.page==='document'?item.destination.document_id+'~'+item.destination.id:item.destination.id)}><div><strong>{item.title}</strong><small className="block muted">{item.label} · {date(item.created_at)}</small></div><span className="next-action">{item.action} →</span></button>)}</div>:<Empty text="当前没有待处理任务" detail="开始生成或保存编辑进度后，可以从这里继续。"/>}</section>;
}
