'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import type {User,Version} from '../lib/types';
import {api} from '../lib/api';
import {Modal,useAction} from './ui';

export function ReviewSubmitModal({versions,close,complete,unresolvedCount=0,expectedPackId}:{versions:Version[];close:()=>void;complete?:()=>void;unresolvedCount?:number;expectedPackId?:string}){
 const {data:reviewers=[]}=useQuery({queryKey:['reviewers'],queryFn:()=>api<User[]>('/reviewers')});
 const [ids,setIds]=useState<string[]>([]);const [note,setNote]=useState('');const [busy,setBusy]=useState(false);const {perform}=useAction();
 const creators=new Set(versions.map(v=>v.creator_id));
 return <Modal title={versions.length>1?'批量提交审核':'提交审核'} close={()=>{if(!busy)close();}}><form onSubmit={async e=>{e.preventDefault();if(busy)return;setBusy(true);const result=await perform(()=>api('/documents/batch-submit','POST',{version_ids:versions.map(v=>v.id),expected_revisions:Object.fromEntries(versions.map(v=>[v.id,v.revision])),reviewer_ids:ids,note,...(expectedPackId?{expected_pack_id:expectedPackId}:{})}),`已提交 ${versions.length} 份文件，等待审核`);setBusy(false);if(result){complete?.();close();}}}><div className="form-fields"><p className="notice">选中 {versions.length} 份文件。提交后锁定版本，所有指定审核员通过且索引构建成功后，文件成为正式可检索知识。</p><div className="review-submit-files">{versions.map(v=><p key={v.id}>{v.filename} · {v.label}</p>)}</div><p className="muted small">整批校验后提交；任一文件不符合条件时全部不提交。最多50份，不能选择提交人或文件创建人为审核员。</p>{unresolvedCount>0&&<p className="notice">仍有 {unresolvedCount} 项澄清待处理，请核对正文。</p>}<fieldset disabled={busy}><legend>选择审核员（至少一名）</legend>{reviewers.map(r=><label className="checkbox-label" key={r.id}><input type="checkbox" disabled={creators.has(r.id)} checked={ids.includes(r.id)} onChange={e=>setIds(e.target.checked?[...ids,r.id]:ids.filter(id=>id!==r.id))}/>{r.display_name} <small>@{r.username}{creators.has(r.id)?' · 文件创建人，不可自审':''}</small></label>)}{!reviewers.some(r=>!creators.has(r.id))&&<p className="notice">没有可用的其他审核员，请由管理员配置审核人员。</p>}</fieldset><label>提交说明<textarea rows={3} disabled={busy} value={note} onChange={e=>setNote(e.target.value)} maxLength={10000}/></label></div><footer><button type="button" className="secondary" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={busy||!ids.length||!versions.length||versions.length>50}>{busy?'正在提交…':'确认提交审核'}</button></footer></form></Modal>;
}
