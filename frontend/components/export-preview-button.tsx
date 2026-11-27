'use client';
import {useState,useEffect} from 'react';
import {csrfHeaders} from '../lib/api';
import {readJsonResponse} from '../lib/http';
import {Modal} from './ui';

export function ExportPreviewButton({versionId}:{versionId:string}){
 const [busy,setBusy]=useState(false);const [url,setUrl]=useState('');const [error,setError]=useState('');const [report,setReport]=useState<{pages:number;warnings:string[]}|null>(null);
 useEffect(()=>()=>{if(url)URL.revokeObjectURL(url);},[url]);
 async function open(){setBusy(true);setError('');try{const response=await fetch('/api/versions/'+versionId+'/export-preview',{method:'POST',credentials:'include',headers:await csrfHeaders()});if(!response.ok){await readJsonResponse(response);return;}const meta=response.headers.get('X-Export-Check');setReport(meta?JSON.parse(meta):null);setUrl(URL.createObjectURL(await response.blob()));}catch(reason){setError(reason instanceof Error?reason.message:'排版预览生成失败');}finally{setBusy(false);}}
 return <><button className="secondary" disabled={busy} onClick={()=>void open()}>{busy?'正在渲染分页…':'Word 排版预览'}</button>{error&&<p className="form-error" role="alert">{error}</p>}{url&&<Modal title="Word 实际排版预览" close={()=>setUrl('')} wide><div className="form-fields"><p>共 {report?.pages||'—'} 页。请核对标题、表格、分页与页眉页脚；排版检查不能替代内容审核。</p>{report?.warnings.map((w,i)=><p key={i} className="notice">{w}</p>)}<iframe title="文档分页预览" src={url} style={{width:'100%',height:'65vh',border:0}}/><a className="secondary" href={url} download="requirements-preview.pdf">下载排版预览 PDF</a></div></Modal>}</>;
}
