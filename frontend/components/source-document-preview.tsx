'use client';

import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {api} from '../lib/api';
import {Loading} from './ui';

type WordBlock = {kind:'text';parts:(string|number)[];heading:boolean;align:string}
  | {kind:'table';rows:WordBlock[][][]};
type Preview = {kind:'spreadsheet';sheets:string[];sheet:number;offset:number;rows:string[][];columns:number;has_more:boolean;columns_limited:boolean}
  | {kind:'word';blocks:WordBlock[];omitted_images:number}
  | {kind:'pdf';pages:number};

export const hasSourcePreview = (filename:string) => /\.(xlsx|xls|csv|docx|doc|pdf)$/i.test(filename);

function columnName(index:number):string {
  return (index>=26?columnName(Math.floor(index/26)-1):'')+String.fromCharCode(65+index%26);
}

function WordBlocks({blocks,endpoint}:{blocks:WordBlock[];endpoint:string}) {
  return blocks.map((block,i)=>{
    if(block.kind==='table') return <div className="table-wrap" key={i}><table><tbody>{block.rows.map((row,j)=><tr key={j}>
      {row.map((cell,k)=><td key={k}><WordBlocks blocks={cell} endpoint={endpoint}/></td>)}
    </tr>)}</tbody></table></div>;
    const Tag=block.heading?'h3':'p';
    const align=block.align==='center'||block.align==='right'||block.align==='justify'?block.align:undefined;
    return <Tag key={i} style={{textAlign:align,whiteSpace:'pre-wrap'}}>{block.parts.length?block.parts.map((part,j)=>typeof part==='string'?part:
      // The image route requires access to this version and returns validated raster content.
      // eslint-disable-next-line @next/next/no-img-element
      <img key={j} src={endpoint+'/image/'+part} alt={'文档图片 '+(part+1)} loading="lazy"/>) : <br/>}</Tag>;
  });
}

export function SourceDocumentPreview({versionId,filename,content}: {versionId:string;filename:string;content:string}) {
  const [sheet,setSheet]=useState(-1);
  const [offset,setOffset]=useState(0);
  const [page,setPage]=useState(1);
  const endpoint='/versions/'+versionId+'/source-preview';
  const supported=hasSourcePreview(filename);
  const {data,isLoading,error}=useQuery({queryKey:['source-preview',versionId,filename,sheet,offset],enabled:supported,
    queryFn:()=>api<Preview>(endpoint+'?sheet='+sheet+'&offset='+offset),staleTime:60_000,retry:false});
  if(!supported||error) return <>
    {error&&<p className="notice">{error.message}</p>}
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content||'当前无可显示的解析文本。'}</ReactMarkdown>
  </>;
  if(isLoading||!data) return <Loading/>;
  const sourceUrl='/api'+endpoint;

  if(data.kind==='word') return <>
    {data.omitted_images>0&&<p className="notice">有 {data.omitted_images} 张图片需要下载原文件查看。</p>}
    <WordBlocks blocks={data.blocks} endpoint={sourceUrl}/>
  </>;

  if(data.kind==='pdf') return <div className="source-pdf-preview">
    <div className="button-group">
      <button type="button" className="secondary" disabled={page<=1} onClick={()=>setPage(page-1)}>上一页</button>
      <span aria-live="polite">第 {page} / {data.pages} 页</span>
      <button type="button" className="secondary" disabled={page>=data.pages} onClick={()=>setPage(page+1)}>下一页</button>
    </div>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img key={page} src={sourceUrl+'/page/'+page} alt={'PDF 第 '+page+' 页'} />
    {content&&<details><summary>查看可检索文本</summary><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></details>}
  </div>;

  return <div className="source-sheet-preview">
    <label>工作表<select value={data.sheet} onChange={event=>{setSheet(Number(event.target.value));setOffset(0);}}>
      {data.sheets.map((name,i)=><option key={name} value={i}>{name}</option>)}
    </select></label>
    {data.columns_limited&&<p className="notice">预览显示前 {data.columns} 列，完整表格可下载查看。</p>}
    {data.rows.length ? <div className="table-wrap" tabIndex={0}><table aria-label={data.sheets[data.sheet]}>
      <thead><tr><th scope="col">行号</th>{Array.from({length:data.columns},(_,i)=><th key={i} scope="col">{columnName(i)}</th>)}</tr></thead>
      <tbody>{data.rows.map((row,i)=><tr key={i}><th scope="row">{data.offset+i+1}</th>
        {Array.from({length:data.columns},(_,j)=><td key={j}>{row[j]||''}</td>)}
      </tr>)}</tbody>
    </table></div> : <p className="muted">此工作表暂无内容。</p>}
    <div className="button-group">
      <button type="button" className="secondary" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-50))}>上一页</button>
      {data.rows.length>0&&<span aria-live="polite">第 {offset+1}–{offset+data.rows.length} 行</span>}
      <button type="button" className="secondary" disabled={!data.has_more} onClick={()=>setOffset(offset+data.rows.length)}>下一页</button>
    </div>
  </div>;
}
