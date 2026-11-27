'use client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {Citation,QaMode,QaScope,RetrievalMeta} from '../lib/types';
import {Citations} from './knowledge';

const scopes:Record<QaScope,string>={formal:'正式知识',mine:'我的已解析资料',selected:'所选文件'};

export function splitStoredAnswer(content:string,mode:QaMode='knowledge'){
 const originalQuotes:string[]=[];
 // Older validated answers stored the source quotes as indented Markdown below each claim.
 if(!/^### (资料记载与规则依据|潜在影响与推导|建议核实)\r?\n/.test(content))return {answer:content,originalQuotes};
 const answer=content.replace(/^(.*(〔来源[\d、]+〕))[ \t]*(\r?\n  > 原文：[^\r\n]*(?:\r?\n  > [^\r\n]*)*)/gm,
  (_,claim,references,quotes)=>{
   originalQuotes.push(`${references}\n\n${quotes.trimStart().replace(/^ {2}/gm,'')}`);
   return claim;
  });
 return {answer:mode==='knowledge'?answer.replace(/^### 资料记载与规则依据\r?\n\r?\n/,''):answer,originalQuotes};
}

export function AnswerEvidence({meta,citations=[],candidates=[],originalQuotes=[],openCitation}:{
 meta?:RetrievalMeta|null;
 citations?:Citation[];
 candidates?:Citation[];
 originalQuotes?:string[];
 openCitation:(citation:Citation)=>void;
}){
 if(!meta&&!citations.length&&!candidates.length&&!originalQuotes.length)return null;
 return <details className="qa-evidence">
  <summary>查看依据{citations.length>0&&`（${citations.length} 条引用）`}</summary>
  {citations.length>0&&<Citations citations={citations} open={openCitation}/>}
  {originalQuotes.length>0&&<div className="markdown qa-original-quotes">
   {originalQuotes.map((quote,i)=><ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>{quote}</ReactMarkdown>)}
  </div>}
  {meta&&<RetrievalInfo meta={meta}/>}
  {candidates.length>0&&<details className="qa-candidates">
   <summary>检索候选（{candidates.length} 条，供核对）</summary>
   <Citations citations={candidates} open={openCitation}/>
  </details>}
 </details>;
}

function RetrievalInfo({meta}:{meta:RetrievalMeta}){
 return <div className="qa-retrieval">
  <strong>检索说明</strong>
  <span>范围：{meta.scopes?.map(s=>scopes[s]).join('、')||'默认范围'}</span>
  {meta.document_count!==undefined&&<span>检索采用 {meta.document_count} 份文档，{meta.evidence_count||0} 条候选依据；{meta.unreviewed_count||0} 份未审核资料／记录</span>}
  {meta.retrieval&&<small>{meta.retrieval}</small>}
  {meta.comparison_versions?.map((v,i)=><span key={v.id}>{i===0?'左':'右'}：{v.title} · {v.version}（{v.filename}）</span>)}
  {meta.coverage&&<p className={meta.coverage.complete?'muted':'form-error'}>比较覆盖：{meta.coverage.covered_blocks} / {meta.coverage.changed_blocks} 个变化块；{meta.coverage.complete?'完整覆盖':'部分覆盖，不能视为全文比较'}</p>}
  {meta.notice&&<p>{meta.notice}</p>}
  {meta.warnings?.map((warning,i)=><p key={i}>{warning}</p>)}
 </div>;
}
