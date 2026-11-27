'use client';

import {useState} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {api} from '../lib/api';
import {parseWorkspaceMarkdown} from './rich-text-editor';
import {useAction} from './ui';

type Suggestion={id:number;section:string;before:string;after:string;reason:string};
export type LocalChangePlan={items:Suggestion[];unresolved:string[];format:'rich'|'markdown'};

export function SpecificationLocalChange({id,plan,openEditor}:{id:string;plan:LocalChangePlan;openEditor:()=>void}) {
 const {perform}=useAction();
 const [selected,setSelected]=useState<number[]>([]);
 const [replacements,setReplacements]=useState<Record<number,string>>({});
 const [editing,setEditing]=useState<number|null>(null);
 const [busy,setBusy]=useState(false);

 async function openDraft() {
  if(busy)return;
  setBusy(true);
  const result=await perform(()=>{
   const changes=plan.items.filter(item=>selected.includes(item.id)).map(item=>{
    const replacement=replacements[item.id]??item.after;
    return {id:item.id,replacement,content_json:plan.format==='rich'&&replacement.trim()
     ?parseWorkspaceMarkdown(replacement):null};
   });
   return api('/agent-runs/'+id+'/apply-local-change','POST',{changes});
  },selected.length?'已将所选建议写入草稿':'软需草稿已创建');
  setBusy(false);
  if(result)openEditor();
 }

 return <section className="panel form-fields" aria-label="局部变更建议">
  <div className="task-launch-heading"><h2>局部变更建议</h2><span className="muted">已选 {selected.length} / {plan.items.length} 条</span></div>
  {plan.items.length===0&&<p>本次没有可直接应用的建议。可核对待确认事项，或打开草稿手动编辑。</p>}
  {plan.items.map((item,index)=><article className="local-change-suggestion" key={item.id}>
   <label className="checkbox-label"><input type="checkbox" checked={selected.includes(item.id)} disabled={busy}
    onChange={event=>setSelected(current=>event.target.checked?[...current,item.id]:current.filter(id=>id!==item.id))}/>
    采纳第 {item.id} 条 · {item.section}</label>
   {item.reason&&<p>{item.reason}</p>}
   <details open={index===0}><summary>查看修改前后</summary>
    <div className="local-change-comparison">
     <section><h3>修改前</h3><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.before||'（空白）'}</ReactMarkdown></div></section>
     <section><h3>修改后</h3><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{(replacements[item.id]??item.after)||'（删除此处内容）'}</ReactMarkdown></div></section>
    </div>
    <button type="button" className="text-button" disabled={busy} onClick={()=>setEditing(editing===item.id?null:item.id)}>
     {editing===item.id?'完成编辑':'编辑这条建议'}</button>
    {editing===item.id&&<label>修改后内容（Markdown）<textarea aria-label={'编辑第 '+item.id+' 条建议'} rows={5}
     maxLength={20000} disabled={busy} value={replacements[item.id]??item.after}
     onChange={event=>setReplacements(current=>({...current,[item.id]:event.target.value}))}/></label>}
   </details>
  </article>)}
  {plan.unresolved.length>0&&<section><h3>待确认事项</h3><ul>{plan.unresolved.map(item=><li key={item}>{item}</li>)}</ul></section>}
  <div className="button-group"><button type="button" className="primary" disabled={busy} onClick={()=>void openDraft()}>
   {busy?'正在创建草稿…':selected.length?`应用所选 ${selected.length} 条并编辑`:'打开草稿手动编辑'}</button></div>
 </section>;
}
