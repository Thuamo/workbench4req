'use client';

import {useState} from 'react';
import {Download} from 'lucide-react';
import type {Run} from '../lib/types';

type Node={label:string;detail:string;status:'confirmed'|'conflict'|'pending';citations:string[];children:Node[]};
type MindMap={title:string;branches:Node[];notes:string[];node_count:number;svg_hash:string|null;render_status:string;
 sources:{key:string;title:string;revision:string;truncated:boolean}[]};

const statusLabels={confirmed:'',conflict:'冲突',pending:'待确认'};

function markdownText(text:string) {
 return text.replace(/\s+/g,' ').trim().replace(/[\\`*_\[\]{}()#+.!<>|~&=\-]/g,'\\$&');
}

function downloadOutline(map:MindMap) {
 const lines=['# '+markdownText(map.title),''];
 function appendNodes(nodes:Node[],level:number) {
  for(const node of nodes){
   const status=statusLabels[node.status];
   const sources=node.citations.length?'（来源 '+node.citations.join('、')+'）':'';
   const detail=node.detail?' — '+markdownText(node.detail):'';
   lines.push('  '.repeat(level)+'- '+(status?'**'+status+'**　':'')+markdownText(node.label)+sources+detail);
   appendNodes(node.children,level+1);
  }
 }
 appendNodes(map.branches,0);
 if(map.notes.length)lines.push('','## 备注','',...map.notes.map(note=>'- '+markdownText(note)));
 lines.push('','## 所选资料','',...map.sources.map(source=>
  '- '+source.key+' '+markdownText(source.title)+' · '+markdownText(source.revision)+(source.truncated?'（采用前段内容）':'')),'');
 const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'}));
 const link=document.createElement('a');
 link.href=url;
 link.download='mind-map.md';
 link.click();
 window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function Branches({nodes}:{nodes:Node[]}) {
 return <ul className="mind-map-branches">{nodes.map((node,index)=><li key={index}>
  <div><strong>{node.label}</strong>{node.status!=='confirmed'&&<span className={'mind-map-status '+node.status}>{statusLabels[node.status]}</span>}
   {node.citations.length>0&&<small className="muted">来源 {node.citations.join('、')}</small>}</div>
  {node.detail&&<p>{node.detail}</p>}
  {node.children.length>0&&<Branches nodes={node.children}/>}
 </li>)}</ul>;
}

export function MindMapResult({run}:{run:Run}) {
 const map=run.result.mind_map as unknown as MindMap|undefined;
 if(!map)return null;
 return <MapOutput key={run.id} map={map} runId={run.id}/>;
}

function MapOutput({map,runId}:{map:MindMap;runId:string}) {
 const [previewFailed,setPreviewFailed]=useState(false);
 const svg='/api/agent-runs/'+runId+'/mind-map.svg';
 return <section className="form-fields">
  <h2>{map.title}</h2>
  <div className="button-group">
   <button type="button" className="secondary" onClick={()=>downloadOutline(map)}><Download size={16}/>下载 Markdown 大纲</button>
   {map.svg_hash&&<a className="secondary" href={svg} download="mind-map.svg"><Download size={16}/>下载 SVG 导图</a>}
  </div>
  {map.svg_hash&&!previewFailed&&
   // eslint-disable-next-line @next/next/no-img-element
   <img className="mind-map-preview" src={svg} alt={map.title+'的思维导图'} onError={()=>setPreviewFailed(true)}/>}
  {(map.render_status||previewFailed)&&<p className="muted" role="status">SVG 预览暂不可用，可查看树状大纲并下载 Markdown。</p>}
  <details open={!map.svg_hash||previewFailed||undefined}><summary>树状大纲（{map.node_count} 个节点）</summary>
   <Branches nodes={map.branches}/>
  </details>
  {map.notes.length>0&&<section><h3>备注</h3><ul>{map.notes.map((note,index)=><li key={index}>{note}</li>)}</ul></section>}
  <details><summary>所选资料（{map.sources.length} 项）</summary>
   <ul>{map.sources.map(source=><li key={source.key}>{source.key} {source.title} · {source.revision}
    {source.truncated?'（采用前段内容）':''}</li>)}</ul>
  </details>
 </section>;
}
