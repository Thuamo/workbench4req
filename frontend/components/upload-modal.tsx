'use client';
import {useRef,useState,type ReactNode} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Upload,X} from 'lucide-react';
import {api} from '../lib/api';
import type {Base,Folder,Version} from '../lib/types';
import {Modal,SearchSelect,useAction} from './ui';
import {folderLabel} from './document-choices';

type Entry={id:string;file:File;title:string;status:'pending'|'uploading'|'uploaded'|'failed';error:string};
const documentExtensions=['.pdf','.docx','.doc','.xlsx','.xls','.pptx','.txt','.md','.csv'];
const sourceExtensions=['.py','.java','.kt','.cs','.js','.jsx','.ts','.tsx','.go','.rs','.cpp','.c','.h',
 '.json','.yaml','.yml','.toml','.xml','.sql','.puml','.plantuml','.mmd'];
const names={pending:'待上传',uploading:'正在上传',uploaded:'已上传',failed:'上传失败'};
export function UploadModal({bases,defaultBase,folderId='',close,requirementId,packScope,sourceControl,includeSourceFiles=false,maxFiles,onUploaded}:{
 bases:Base[];defaultBase:string;folderId?:string;close:()=>void;requirementId?:string;
 packScope?:{id:string;stage:string;label:string};sourceControl?:ReactNode;includeSourceFiles?:boolean;
 maxFiles?:number;onUploaded?:(versionId:string)=>void;
}){
 const [baseId,setBaseId]=useState(defaultBase);const [label,setLabel]=useState('V1.0');const [folder,setFolder]=useState(folderId);
 const [entries,setEntries]=useState<Entry[]>([]);const [busy,setBusy]=useState(false);const running=useRef(false);const {perform}=useAction();
 const {data:folders=[]}=useQuery({queryKey:['folders',baseId],queryFn:()=>api<Folder[]>('/knowledge-bases/'+baseId+'/folders'),enabled:!!baseId});
 const extensions=includeSourceFiles?[...documentExtensions,...sourceExtensions]:documentExtensions;
 const remaining=entries.filter(e=>e.status!=='uploaded');const uploaded=entries.filter(e=>e.status==='uploaded').length;
 const tooManyFiles=maxFiles!==undefined&&remaining.length>maxFiles;
 function update(id:string,value:Partial<Entry>){setEntries(rows=>rows.map(row=>row.id===id?{...row,...value}:row));}
 async function send(){
  if(running.current||!remaining.length||tooManyFiles)return;running.current=true;setBusy(true);
  const batch=remaining;let failed=0;
  try{
   await perform(async()=>{
    for(const entry of batch){
     update(entry.id,{status:'uploading',error:''});
     try{
      if(!entry.file.size)throw new Error('文件为空，请重新选择');
      if(entry.file.size>30*1024*1024)throw new Error('单个文件不能超过30MB');
      if(!extensions.some(extension=>entry.file.name.toLowerCase().endsWith(extension)))throw new Error('不支持的文件类型');
      const data=new FormData();data.append('file',entry.file);data.append('title',entry.title.trim()||entry.file.name);data.append('label',label);data.append('base_id',baseId);
      if(folder)data.append('folder_id',folder);
      if(requirementId){data.append('requirement_id',requirementId);data.append('kind','business');}
      if(packScope){data.append('pack_id',packScope.id);data.append('pack_stage',packScope.stage);}
      const version=await api<Pick<Version,'id'>>('/documents/upload','POST',data);
      update(entry.id,{status:'uploaded'});
      onUploaded?.(version.id);
     }catch(reason){failed++;update(entry.id,{status:'failed',error:reason instanceof Error?reason.message:'上传失败，请重试'});}
    }
    return {uploaded:batch.length-failed,failed};
   },'上传处理完成；成功文件的解析状态会自动更新，失败文件可单独重试');
   if(!failed)close();
  }finally{running.current=false;setBusy(false);}
 }
 return <Modal title={packScope?'关联文档':'上传知识文件'} close={()=>{if(!running.current)close();}}><form onSubmit={e=>{e.preventDefault();void send();}}>
  <fieldset className="form-fields upload-fields" disabled={busy}>
   {packScope&&<p className="notice">关联位置 · {packScope.label}</p>}
   {sourceControl}
   {tooManyFiles&&<p className="form-error" role="alert">本次任务还能添加 {maxFiles} 个文件，请移除多选的文件后再上传。</p>}
   <label className="drop-zone"><Upload size={28}/><strong>{entries.length?'已选择 '+entries.length+' 个文件 · 点击继续添加':'选择业务需求或知识文件（支持多选）'}</strong><small>{includeSourceFiles?"支持需求文档、常见源码、配置与图源":"PDF、Word、Excel、PPTX、TXT、Markdown、CSV"} · 每个文件最大30MB</small><input type="file" multiple accept={extensions.join(",")} onChange={e=>{const chosen=Array.from(e.target.files||[]);setEntries(rows=>{const known=new Set(rows.map(r=>r.file.name+'|'+r.file.size+'|'+r.file.lastModified));return [...rows,...chosen.filter(file=>!known.has(file.name+'|'+file.size+'|'+file.lastModified)).map(file=>({id:crypto.randomUUID(),file,title:file.name.replace(/\.[^.]+$/,''),status:'pending' as const,error:''}))];});e.target.value='';}}/></label>
   <div className="upload-queue">{entries.map(entry=><section className="upload-entry" key={entry.id}><div className="upload-entry-heading"><strong>{entry.file.name}</strong><small>{(entry.file.size/1024/1024).toFixed(2)} MB · {names[entry.status]}</small>{entry.status!=='uploaded'&&<button type="button" className="icon-button" aria-label={'移除 '+entry.file.name} onClick={()=>setEntries(rows=>rows.filter(r=>r.id!==entry.id))}><X size={16}/></button>}</div><label>文档资产名称<input aria-label={entries.length===1?'文档资产名称':'文档资产名称：'+entry.file.name} value={entry.title} maxLength={300} required disabled={entry.status==='uploaded'} onChange={e=>update(entry.id,{title:e.target.value})}/></label>{entry.error&&<p className="form-error">{entry.error}</p>}</section>)}</div>
   <div className="form-grid"><label>目标知识库<SearchSelect value={baseId} disabled={uploaded>0} onChange={e=>{setBaseId(e.target.value);setFolder('');}} required>{bases.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</SearchSelect></label><label>业务版本<input value={label} maxLength={80} disabled={uploaded>0} onChange={e=>setLabel(e.target.value)} required/></label></div>
   <label>目录<SearchSelect value={folder} disabled={uploaded>0} onChange={e=>setFolder(e.target.value)}><option value="">根目录</option>{folders.map(f=><option value={f.id} key={f.id}>{folderLabel(f,folders)}</option>)}</SearchSelect></label>
   <p className="document-location">文件位置：{bases.find(b=>b.id===baseId)?.name} / {folders.find(f=>f.id===folder)?folderLabel(folders.find(f=>f.id===folder)!,folders):'根目录'}</p>
   {busy&&<p className="notice" role="status">正在上传文件：已完成 {uploaded} / {entries.length}。请稍候，上传完成后自动更新解析状态。</p>}
   {!busy&&uploaded>0&&<p className="notice">已上传 {uploaded} / {entries.length} 个文件。重试只上传失败或待上传文件，成功文件不会重复上传。</p>}
   <p className="notice">每个文件创建独立文档，统一使用所选知识库、目录和版本。上传后进入暂存区，正式检索仍需审核发布。</p>
  </fieldset><footer><button type="button" className="secondary" disabled={busy} onClick={close}>{uploaded?'完成并返回':'取消'}</button><button className="primary" disabled={busy||!remaining.length||tooManyFiles}>{busy?'上传中…':uploaded?'重试未成功文件':packScope?'上传并关联':'上传并解析'}</button></footer>
 </form></Modal>;
}
