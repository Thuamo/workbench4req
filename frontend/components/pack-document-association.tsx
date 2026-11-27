'use client';

import {useState} from 'react';
import {api} from '../lib/api';
import type {Base} from '../lib/types';
import {DocumentChoices,useSelectableDocuments} from './document-choices';
import {Loading,Modal,Tabs,useAction} from './ui';
import {UploadModal} from './upload-modal';

const modes=[{key:'new',label:'上传新文档'},{key:'existing',label:'关联已上传文档'}];

export function AssociatePackDocuments({requirementId,scope,bases,excludedIds,close,onAssociated,max}: {
 requirementId:string;
 scope:{id:string;stage:string;label:string};
 bases:Base[];
 excludedIds:string[];
 close:()=>void;
 onAssociated:(ids:string[])=>void;
 max:number;
}) {
 const [mode,setMode]=useState('existing');
 const [versionIds,setVersionIds]=useState<string[]>([]);
 const [busy,setBusy]=useState(false);
 const {perform}=useAction();
 const {data:available=[],isLoading,error}=useSelectableDocuments();
 const excluded=new Set(excludedIds);
 const choices=available
  .filter(doc=>scope.stage==='consolidation'||doc.kind==='business'||doc.kind==='reference')
  .map(doc=>({...doc,versions:doc.versions.filter(v=>!excluded.has(v.id))}))
  .filter(doc=>doc.versions.length);
 const readyIds=new Set(choices.flatMap(doc=>doc.versions.filter(v=>v.parse_status==='ready').map(v=>v.id)));
 const selectedIds=versionIds.filter(id=>readyIds.has(id));
 const enabledBases=bases.filter(base=>base.enabled);

 if(mode==='new'&&enabledBases.length)return <UploadModal bases={enabledBases} defaultBase={enabledBases[0].id}
  close={close} requirementId={requirementId} packScope={scope} includeSourceFiles maxFiles={max}
  onUploaded={id=>onAssociated([id])}
  sourceControl={<Tabs value={mode} onChange={setMode} items={modes}/>}/>;

 return <Modal title="关联文档" close={()=>{if(!busy)close();}}>
  <div className="form-fields">
   <p className="notice">关联位置 · {scope.label}</p>
   <Tabs value={mode} onChange={value=>{if(!busy)setMode(value);}} items={modes}/>
   {mode==='new'?<p>当前没有可用的知识库，可切换为关联已上传文档。</p>:
    isLoading?<Loading/>:error?<p className="form-error">{error.message}</p>:
    <DocumentChoices documents={choices} value={selectedIds} onChange={setVersionIds} max={max}/>}
  </div>
  <footer>
   <button className="secondary" disabled={busy} onClick={close}>取消</button>
   {mode==='existing'&&<button className="primary" disabled={busy||!selectedIds.length||selectedIds.length>max} onClick={async()=>{
    setBusy(true);
    const result=await perform(()=>api<{version_ids:string[]}>(`/requirements/${requirementId}/packs/${scope.id}/stages/${scope.stage}/documents`,
     'POST',{version_ids:selectedIds}),'已加入本次任务的输入资料');
    setBusy(false);
    if(result){
     onAssociated(result.version_ids);
     close();
    }
   }}>确认关联</button>}
  </footer>
 </Modal>;
}
