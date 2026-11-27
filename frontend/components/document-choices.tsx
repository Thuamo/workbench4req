'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Folder,Loader2} from 'lucide-react';
import {api} from '../lib/api';
import type {Document,Folder as FolderType} from '../lib/types';
import {Badge,SearchBox,Empty} from './ui';

export const documentLocation=(document:Document)=>document.location_path||document.base_name||'知识库 / 根目录';
export function folderLabel(folder:FolderType,folders:FolderType[]){
 const path=[folder.name];const seen=new Set([folder.id]);let parent=folder.parent_id;
 while(parent&&!seen.has(parent)){seen.add(parent);const item=folders.find(f=>f.id===parent&&f.base_id===folder.base_id);if(!item)break;path.unshift(item.name);parent=item.parent_id;}
 return path.join(' / ');
}
export function useSelectableDocuments(){
 return useQuery({queryKey:['documents-all'],queryFn:()=>api<Document[]>('/documents'),
  refetchInterval:query=>query.state.data?.some(d=>d.versions.some(v=>!['ready','failed'].includes(v.parse_status)))?1500:false});
}

// Every node uses IDs for identity, so folders with the same name stay separate.
type Node={name:string;path:string;children:Map<string,Node>;documents:Document[]};
export function DocumentChoices({documents,value,onChange,max,single=false}:{documents:Document[];value:string[];onChange:(ids:string[])=>void;max?:number;single?:boolean}){
 const [search,setSearch]=useState('');
 const root:Node={name:'',path:'',children:new Map(),documents:[]};
 for(const document of documents){
  if(search&&!`${document.title} ${documentLocation(document)} ${document.versions.map(v=>v.filename+' '+v.label).join(' ')}`.toLowerCase().includes(search.toLowerCase()))continue;
  let node=root;
  const parts=[{id:document.base_id,name:document.base_name||'知识库'},...(document.folder_path?.length?document.folder_path:[{id:'root',name:'根目录'}])];
  for(const part of parts){if(!node.children.has(part.id))node.children.set(part.id,{name:part.name,path:[node.path,part.name].filter(Boolean).join(' / '),children:new Map(),documents:[]});node=node.children.get(part.id)!;}
  node.documents.push(document);
 }
 function render(node:Node){return <>{Array.from(node.children.entries()).map(([id,child])=><details open key={id} className="document-directory"><summary><Folder size={15}/>{child.name}</summary><div>{render(child)}</div></details>)}{node.documents.map(document=><div key={document.id} className="document-choice-asset">{document.versions.map(version=>{
  const ready=version.parse_status==='ready';const failed=version.parse_status==='failed';const checked=value.includes(version.id);
  return <label className={'checkbox-label document-choice '+(!ready?'unavailable':'')} key={version.id}><input type={single?'radio':'checkbox'} checked={checked} disabled={!ready||!checked&&max!==undefined&&value.length>=max} onChange={e=>onChange(single?[version.id]:e.target.checked?[...value,version.id]:value.filter(id=>id!==version.id))}/><span><strong>{document.title} {version.label}</strong> <Badge state={version.status}/><small className="document-location">位置：{documentLocation(document)} / {version.filename}</small>{!ready&&<small className={failed?'form-error':'parse-progress'}>{!failed&&<Loader2 size={13} className="spin"/>}{failed?'解析失败，请在知识库中打开文件重试':'正在解析，完成后即可选择（自动刷新）'}</small>}</span></label>;
 })}</div>)}</>;}
 return <div className="document-choices"><SearchBox value={search} onChange={setSearch} placeholder="搜索文件名称或目录位置"/>{root.children.size?render(root):<Empty text={search?'没有匹配的文件':'暂无文件，请先上传'}/>}</div>;
}
