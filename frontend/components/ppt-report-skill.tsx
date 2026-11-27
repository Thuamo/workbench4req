'use client';

import {useState} from 'react';
import {Download} from 'lucide-react';
import type {Run} from '../lib/types';

type Output={headline:string;context:string;sections:{heading:string;detail:string;citations:string[]}[];
 speaker_notes:string[];sources:{key:string;title:string;revision:string;truncated:boolean}[]};

export function PptReportResult({run}:{run:Run}) {
 const report=run.result.ppt_report as unknown as Output|undefined;
 if(!report)return null;
 return <ReportOutput key={run.id} runId={run.id} report={report}/>;
}

function ReportOutput({runId,report}:{runId:string;report:Output}) {
 const [attempt,setAttempt]=useState(0);
 const [preview,setPreview]=useState<'loading'|'ready'|'error'>('loading');
 const endpoint='/api/agent-runs/'+runId;
 return <section className="form-fields">
  <div className="button-group"><a className="primary" href={endpoint+'/report.pptx'} download>
   <Download size={16}/>下载一页 PPTX</a></div>
  {preview==='loading'&&<p role="status" className="muted">正在加载 PPT 预览…</p>}
  {preview==='error'?<div className="notice button-group">
   <span role="status">暂时无法显示 PPT 图片。</span>
   <button type="button" className="text-button" onClick={()=>{setPreview('loading');setAttempt(attempt+1);}}>重试预览</button>
  </div>:
   // eslint-disable-next-line @next/next/no-img-element
   <img className="ppt-report-preview" key={attempt} src={endpoint+'/report-preview.png'+(attempt?'?retry='+attempt:'')}
    alt={'一页汇报 PPT 预览：'+report.headline} hidden={preview!=='ready'} onLoad={()=>setPreview('ready')} onError={()=>setPreview('error')}/>}
  <details className="report-text" open={preview==='error'||undefined}><summary>汇报正文、备注与来源（{report.sources.length} 项）</summary>
   <div><h2>{report.headline}</h2>{report.context&&<p className="muted">{report.context}</p>}</div>
   {report.sections.map((section,index)=><article key={index}>
    <h3>{section.heading}</h3><p>{section.detail}</p><small className="muted">来源 {section.citations.join('、')}</small>
   </article>)}
   {report.speaker_notes.map((note,index)=><p key={index}>{note}</p>)}
   <ul>{report.sources.map(source=><li key={source.key}>
    {source.key} {source.title} · {source.revision}{source.truncated?'（采用前段内容）':''}
   </li>)}</ul>
  </details>
 </section>;
}
