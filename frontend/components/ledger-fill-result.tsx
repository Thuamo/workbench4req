'use client';
import {useState} from 'react';
import {api} from '../lib/api';
import {useAction} from './ui';
import type {Run} from '../lib/types';
import type {PageKey} from './workbench';

type Fields=Record<string,string|number|null>;
type Target={task_id:string|null;fields:Fields};
type Preview={revision:string;columns:string[];fields:Fields;baseline:Target;targets?:Target[]};
const summaryColumns=['需求编号','需求名称','澄清周','澄清时间','会议结论'];
const meetingColumns=['澄清周','澄清时间','澄清结果','会议结论'];
const isRegistered=(value:Fields[string]|undefined)=>value!==undefined&&value!==null&&value!=='';

export function LedgerFillResult({run,navigate}:{run:Run;navigate:(p:PageKey,id?:string)=>void}){
 const preview=run.result.ledger_preview as unknown as Preview|undefined;
 const {perform}=useAction();const [busy,setBusy]=useState(false);
 const savedFields=run.result.saved_ledger_fields as unknown as Fields|undefined;const savedColumns=(run.result.saved_ledger_columns as string[]|undefined)||preview?.columns||[];
 if(run.result.saved_ledger_task_id)return <section className="panel"><h2>台账填报结果</h2><p>内容已确认并写入澄清计划，重复点击不会再次插入。</p>{savedFields&&<details open><summary>已确认24列内容（本次快照）</summary><div className="table-wrap"><table><thead><tr><th>序号</th><th>原表字段</th><th>已确认内容</th></tr></thead><tbody>{savedColumns.map((c,i)=><tr key={c}><td>{i+1}</td><th>{c}</th><td style={{whiteSpace:'pre-wrap'}}>{String(savedFields[c]??'')}</td></tr>)}</tbody></table></div></details>}<button className="primary" onClick={()=>navigate('clarification')}>查看澄清计划</button></section>;
 return <section className="panel ledger-fill-result"><h2>澄清台账24列填报</h2><p>按当前澄清计划的原表列顺序生成。核对内容并确认后入表，同编号已有记录仅补空字段。</p>{preview&&<PreviewForm key={preview.revision} preview={preview} runId={run.id}/>}<button className="secondary" disabled={busy} onClick={async()=>{setBusy(true);await perform(()=>api('/agent-runs/'+run.id+'/ledger-preview','POST'),'24列预览已生成，请核对后确认');setBusy(false);}}>{busy?'正在生成24列内容…':preview?'重新生成预览（将丢弃未确认编辑）':'生成24列填报预览'}</button></section>;
}

function fieldsForTarget(preview:Preview,target:Target|undefined):Fields {
 const fields={...preview.fields};
 if(!target||target.task_id===preview.baseline.task_id)return fields;
 for(const column of preview.columns){
  const existing=target.fields[column];
  const suggested=fields[column];
  if(isRegistered(existing))fields[column]=existing;
  else if(meetingColumns.includes(column)||typeof suggested==='string'&&(suggested.length>10000||/[\t\r\n]/.test(suggested)))fields[column]=null;
 }
 return fields;
}

function PreviewForm({preview,runId}:{preview:Preview;runId:string}){
 const targets=preview.targets??(preview.baseline.task_id?[preview.baseline]:[]);
 const needsSelection=targets.length>1;
 const [targetId,setTargetId]=useState(needsSelection?'':preview.baseline.task_id??'');
 const [drafts,setDrafts]=useState<Record<string,Fields>>({});
 const [busy,setBusy]=useState(false);
 const {perform}=useAction();
 const target=targets.find(row=>row.task_id===targetId);
 const waiting=needsSelection&&!target;
 const fields=drafts[targetId]??fieldsForTarget(preview,target);
 const line=preview.columns.map(c=>{const value=fields[c];const text=String(value??'').replace(/[\t\r\n]+/g,' ');return typeof value==='string'&&/^[=+@-]/.test(text)?"'"+text:text;}).join('\t');
 return <>
  {needsSelection&&<fieldset disabled={busy}>
   <legend>选择要更新的台账记录</legend>
   <p className="muted">本预览参考标记为「生成依据」的最新记录。请选择写入目标，系统会保留该行已登记的内容。</p>
   <div className="table-wrap"><table><thead><tr><th scope="col">选择</th>{summaryColumns.map(column=><th scope="col" key={column}>{column}</th>)}</tr></thead><tbody>
    {targets.map((row,index)=><tr key={row.task_id}>
     <td><label className="checkbox-label"><input type="radio" name={'ledger-target-'+runId} value={row.task_id??''} checked={targetId===row.task_id}
      aria-label={'选择第 '+(index+1)+' 条台账记录'} onChange={()=>setTargetId(row.task_id??'')}/>{row.task_id===preview.baseline.task_id&&<small>生成依据</small>}</label></td>
     {summaryColumns.map(column=><td key={column} style={{whiteSpace:'pre-wrap'}}>{String(row.fields[column]??'')||'—'}</td>)}
    </tr>)}
   </tbody></table></div>
  </fieldset>}
  <p className="notice">{waiting?'选定目标后可编辑待填字段。':target?'已登记非空字段锁定，其余字段可以编辑。':'当前台账没有同编号记录，确认后新增一行。'}未知字段请保持空白。</p>
  <div className="table-wrap"><table><thead><tr><th>序号</th><th>原表字段</th><th>填报内容</th></tr></thead><tbody>
   {preview.columns.map((column,index)=>{const locked=column==='需求编号'||isRegistered((target??preview.baseline).fields[column]);return <tr key={column}>
    <td>{index+1}</td><th>{column}</th><td><input aria-label={'填报 '+column} value={fields[column]??''} readOnly={locked||waiting||busy}
     onChange={e=>{const value=e.target.value;setDrafts(current=>({...current,[targetId]:{...(current[targetId]??fields),[column]:value}}));}}/>
    {locked&&<small className="muted">已登记 / 任务编号</small>}</td>
   </tr>;})}
  </tbody></table></div>
  <details><summary>查看按原表顺序排列的单行 TSV（24列）</summary><pre className="json-view">{line}</pre><button className="secondary" onClick={()=>void perform(()=>navigator.clipboard.writeText(line),'24列TSV已复制，空字段位置保留')}>复制单行TSV</button></details>
  <button className="primary" disabled={busy||waiting} onClick={async()=>{setBusy(true);await perform(()=>api('/agent-runs/'+runId+'/ledger-confirm','POST',{revision:preview.revision,fields,confirm:true,target_task_id:target?.task_id}),'已确认写入澄清计划');setBusy(false);}}>{busy?'正在写入…':'确认内容并写入澄清计划'}</button>
 </>;
}
