'use client';

import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Download,Play} from 'lucide-react';
import {api} from '../lib/api';
import type {Base,Requirement,Run,Skill} from '../lib/types';
import {DocumentChoices,useSelectableDocuments} from './document-choices';
import {UploadModal} from './upload-modal';
import {Modal,useAction} from './ui';

type DiagramType={id:string;label:string;approximate:boolean};
type Diagram={diagram_type:string;label:string;title:string;source:string;notes:string[];citations:string[];
 approximate:boolean;svg_hash:string|null;render_status:string};
type UmlOutput={diagrams:Diagram[];sources:{id:string;filename:string;version:string;truncated:boolean}[]};

export function UmlExecuteModal({skill,close,complete,conversationId,defaultRequirement,defaultTask='',defaultSourceIds=[]}:{
 skill:Skill;close:()=>void;complete:(run:Run)=>void;conversationId?:string;defaultRequirement?:Requirement;
 defaultTask?:string;defaultSourceIds?:string[];
}) {
 const [task,setTask]=useState(defaultTask);
 const [sources,setSources]=useState(defaultSourceIds);
 const [selectedTypes,setSelectedTypes]=useState<string[]>([]);
 const [upload,setUpload]=useState(false);
 const [busy,setBusy]=useState(false);
 const {perform}=useAction();
 const {data:documents=[]}=useSelectableDocuments();
 const {data:bases=[]}=useQuery({queryKey:['bases'],queryFn:()=>api<Base[]>('/knowledge-bases')});
 const {data:types=[],isLoading,error}=useQuery({queryKey:['uml-diagram-types'],queryFn:()=>api<DiagramType[]>('/uml/diagram-types')});

 return <><Modal title={'运行 '+skill.name} close={close} wide>
  <form onSubmit={async event=>{
   event.preventDefault();
   if(busy||!sources.length||!selectedTypes.length)return;
   setBusy(true);
   try {
    const title=types.filter(type=>selectedTypes.includes(type.id)).map(type=>type.label).join('、');
    const run=await perform(()=>api<Run>('/skills/'+skill.id+'/execute','POST',{
     task:task.trim()||'根据所选文件生成'+title,source_version_ids:sources,diagram_types:selectedTypes,
     requirement_id:defaultRequirement?.id||null,conversation_id:conversationId||null,
    }),'UML 图生成任务已进入队列');
    if(run){close();complete(run);}
   } finally {setBusy(false);}
  }}>
   <div className="form-fields">
    <fieldset className="file-source-field"><legend>输入文件（可多选）</legend>
     <button type="button" className="secondary" disabled={!bases.length} onClick={()=>setUpload(true)}>上传新文件</button>
     <DocumentChoices documents={documents} value={sources} onChange={setSources}/>
    </fieldset>
    <fieldset><legend>UML 图种（可多选）</legend>
     {isLoading&&<p role="status">正在加载图种…</p>}
     {error&&<p className="form-error">{error.message}</p>}
     <div className="form-grid">{types.map(type=><label className="checkbox-label" key={type.id}>
      <input type="checkbox" checked={selectedTypes.includes(type.id)} onChange={event=>setSelectedTypes(current=>
       event.target.checked?[...current,type.id]:current.filter(value=>value!==type.id))}/>
      {type.label}{type.approximate&&<small className="muted">（近似表示）</small>}
     </label>)}</div>
    </fieldset>
    <label>建模场景或范围（可选）<textarea rows={3} value={task} onChange={event=>setTask(event.target.value)} maxLength={20000}
     placeholder="例如取消订单，从用户发起请求到保存状态，包含业务拒绝分支"/></label>
   </div>
   <footer><button type="button" className="secondary" onClick={close}>取消</button>
    <button className="primary" disabled={busy||!sources.length||!selectedTypes.length}>
     <Play size={15}/>{busy?'创建中…':'生成 UML 图'}</button>
   </footer>
  </form>
 </Modal>{upload&&<UploadModal bases={bases} defaultBase={bases[0].id} includeSourceFiles close={()=>setUpload(false)}/>}</>;
}

function downloadSource(source:string,filename:string){
 const url=URL.createObjectURL(new Blob([source],{type:'text/plain;charset=utf-8'}));
 const link=document.createElement('a');
 link.href=url;
 link.download=filename;
 link.click();
 window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export function UmlResult({run}:{run:Run}){
 const result=run.result.uml as unknown as UmlOutput|undefined;
 if(!result)return null;
 const sources=new Map(result.sources.map(source=>[source.id,source]));
 return <div className="form-fields">
  <h2>UML 图稿</h2>
  {result.sources.some(source=>source.truncated)&&<p className="notice">
   以下文件超出单次建模上下文，图稿仅采用其前段内容：{result.sources.filter(source=>source.truncated).map(source=>source.filename).join('、')}。
  </p>}
  {result.diagrams.map(diagram=>{
   const filename='uml-'+diagram.diagram_type;
   const image='/api/agent-runs/'+run.id+'/uml/'+diagram.diagram_type+'.svg';
   return <section className="panel form-fields" key={diagram.diagram_type}>
    <div><h3>{diagram.label} · {diagram.title}</h3>{diagram.approximate&&<small className="muted">PlantUML 近似表示</small>}</div>
    {diagram.svg_hash?<div style={{overflow:'auto'}}><img src={image} alt={diagram.title} style={{display:'block',maxWidth:'100%',height:'auto'}}/></div>:
     <p className="notice">{diagram.render_status}</p>}
    <div className="button-group">
     {diagram.source&&<button className="secondary" onClick={()=>downloadSource(diagram.source,filename+'.puml')}><Download size={15}/>下载 PlantUML</button>}
     {diagram.svg_hash&&<a className="secondary" href={image} download={filename+'.svg'}><Download size={15}/>下载 SVG</a>}
    </div>
    {diagram.source&&<details><summary>查看图源</summary><pre style={{overflow:'auto'}}>{diagram.source}</pre></details>}
    {!!diagram.citations.length&&<p>来源 {diagram.citations.map(id=>{const source=sources.get(id);return source?`${id} ${source.filename} · ${source.version}`:id;}).join('、')}</p>}
    {!!diagram.notes.length&&<ul>{diagram.notes.map((note,index)=><li key={index}>{note}</li>)}</ul>}
   </section>;
  })}
 </div>;
}
