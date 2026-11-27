'use client';
import { useState, createContext, useContext, ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {createPortal} from 'react-dom';
import { X, Search, Inbox, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { states } from '../lib/api';
import { SearchSelect } from './search-select';
export { SearchSelect } from './search-select';

export const ActionContext=createContext<{perform:<T>(fn:()=>Promise<T>,message?:string)=>Promise<T|undefined>}>({perform:async fn=>fn()});
export const useAction=()=>useContext(ActionContext);
export function ActionProvider({children}:{children:ReactNode}) {
  const [toast,setToast]=useState<{text:string;error:boolean}|null>(null);
  const query=useQueryClient();
  async function perform<T>(fn:()=>Promise<T>,message='操作已保存'):Promise<T|undefined> {
    try { const result=await fn(); await query.invalidateQueries(); setToast({text:message,error:false}); setTimeout(()=>setToast(null),4500); return result; }
    catch(error) {if(error instanceof Error&&error.name==='AbortError'){await query.invalidateQueries();setToast({text:'已停止生成',error:false});return undefined;}setToast({text:error instanceof Error?error.message:'操作失败',error:true}); return undefined;}
  }
  return <ActionContext.Provider value={{perform}}>{children}{toast&&<div className={'toast '+(toast.error?'error':'')} role="alert">{toast.error?<AlertCircle size={18}/>:<CheckCircle2 size={18}/>}<span>{toast.text}</span><button onClick={()=>setToast(null)} aria-label="关闭通知"><X size={16}/></button></div>}</ActionContext.Provider>;
}
export function Badge({state}:{state:string}) { return <span className={'badge '+state}>{states[state]||state}</span>; }
export function Empty({text='暂无记录',detail='完成相应操作后，记录会显示在这里。'}:{text?:string;detail?:string}) {return <div className="empty"><Inbox size={32}/><strong>{text}</strong><p>{detail}</p></div>;}
export function Loading(){return <div className="loading"><Loader2 className="spin" size={22}/> 正在读取…</div>;}
export function SearchBox({value,onChange,placeholder='搜索'}:{value:string;onChange:(value:string)=>void;placeholder?:string}) {return <div className="search-input"><Search size={16}/><input value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder}/></div>;}
export function Modal({title,children,close,wide=false,returnLabel='返回'}:{title:string;children:ReactNode;close:()=>void;wide?:boolean;returnLabel?:string}) {if(typeof document==='undefined')return null;return createPortal(<div className="modal-shade" onMouseDown={e=>{if(e.target===e.currentTarget)close();}}><section className={'modal '+(wide?'wide':'')} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button type="button" className="secondary modal-return" onClick={close}>{returnLabel}</button><button type="button" className="icon-button" onClick={close} aria-label="关闭"><X size={20}/></button></header>{children}</section></div>,document.body);}
export type FormField={key:string;label:string;type?:'text'|'password'|'textarea'|'json'|'select';options?:{value:string;label:string}[];required?:boolean;hint?:string};
export function FormModal({title,fields,initial={},onSubmit,close}:{title:string;fields:FormField[];initial?:Record<string,unknown>;onSubmit:(data:Record<string,string>)=>Promise<unknown>;close:()=>void}) {
  const [values,setValues]=useState<Record<string,string>>(Object.fromEntries(fields.map(f=>[f.key,f.type==='json'?JSON.stringify(initial[f.key]??{},null,2):String(initial[f.key]??'')])));
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  return <Modal title={title} close={close}><form onSubmit={async e=>{e.preventDefault();const missing=fields.find(f=>f.required&&!values[f.key]?.trim());if(missing){setError('请填写'+missing.label);return;}setBusy(true);setError('');try { const result=await onSubmit(values);if(result!==undefined)close(); }catch(err){setError(err instanceof Error?err.message:'保存失败');}finally{setBusy(false);}}}><div className="form-fields">{fields.map(f=><label key={f.key}>{f.label}{f.type==='select'?<SearchSelect aria-label={f.label} value={values[f.key]} required={f.required} onChange={e=>setValues({...values,[f.key]:e.target.value})}><option value="">请选择</option>{f.options?.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</SearchSelect>:f.type==='textarea'||f.type==='json'?<textarea aria-label={f.label} className={f.type==='json'?'code':''} rows={f.type==='json'?8:4} value={values[f.key]} required={f.required} onChange={e=>setValues({...values,[f.key]:e.target.value})}/>:<input aria-label={f.label} type={f.type==='password'?'password':'text'} value={values[f.key]} required={f.required} onChange={e=>setValues({...values,[f.key]:e.target.value})}/>} {f.hint&&<small>{f.hint}</small>}</label>)}</div>{error&&<p className="form-error">{error}</p>}<footer><button type="button" className="secondary" onClick={close}>取消</button><button className="primary" disabled={busy}>{busy?'保存中…':'保存'}</button></footer></form></Modal>;
}
export function JsonView({value}:{value:unknown}) {return <pre className="json-view">{JSON.stringify(value,null,2)}</pre>;}
export function Tabs({items,value,onChange}:{items:{key:string;label:string}[];value:string;onChange:(key:string)=>void}) {return <div className="tabs">{items.map(i=><button type="button" key={i.key} className={value===i.key?'active':''} onClick={()=>onChange(i.key)}>{i.label}</button>)}</div>;}
