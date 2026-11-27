'use client';

import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Play} from 'lucide-react';
import {api} from '../lib/api';
import {requirementLabel} from '../lib/business-identity';
import type {Base,Requirement,Run,Skill} from '../lib/types';
import {DocumentChoices,useSelectableDocuments} from './document-choices';
import {UploadModal} from './upload-modal';
import {Modal,SearchBox,useAction} from './ui';

export function SelectedMaterialsExecuteModal({skill,close,complete,conversationId,defaultRequirement,defaultTask='',defaultSourceIds=[]}:{
 skill:Skill;close:()=>void;complete:(run:Run)=>void;conversationId?:string;defaultRequirement?:Requirement;
 defaultTask?:string;defaultSourceIds?:string[];
}) {
 const isMindMap=skill.config.workflow==='mind_map';
 const [requirementIds,setRequirementIds]=useState<string[]>(defaultRequirement?[defaultRequirement.id]:[]);
 const [sourceIds,setSourceIds]=useState(defaultSourceIds);
 const [search,setSearch]=useState('');
 const [audience,setAudience]=useState('');
 const [task,setTask]=useState(defaultTask);
 const [busy,setBusy]=useState(false);
 const [upload,setUpload]=useState(false);
 const {perform}=useAction();
 const {data:requirements=[],error:requirementsError}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});
 const {data:documents=[]}=useSelectableDocuments();
 const {data:bases=[]}=useQuery({queryKey:['bases'],queryFn:()=>api<Base[]>('/knowledge-bases')});
 const shown=requirements.filter(requirement=>(!requirement.kind||requirement.kind==='business')&&
  requirementLabel(requirement).toLowerCase().includes(search.trim().toLowerCase()));
 const empty=!requirementIds.length&&!sourceIds.length;

 return <><Modal title={'运行 '+skill.name} close={close} wide>
  <form onSubmit={async event=>{
   event.preventDefault();
   if(empty||busy)return;
   setBusy(true);
   try {
    const run=await perform(()=>api<Run>('/skills/'+skill.id+'/execute','POST',{
     task:task.trim()||(isMindMap?'梳理所选资料并生成思维导图':'根据所选资料生成一页汇报 PPT'),source_version_ids:sourceIds,
     conversation_id:conversationId||null,
     ...(isMindMap?{mind_map_requirement_ids:requirementIds}:{report_requirement_ids:requirementIds,report_audience:audience.trim()}),
    }),isMindMap?'思维导图任务已进入队列':'一页汇报 PPT 任务已进入队列');
    if(run){close();complete(run);}
   } finally {setBusy(false);}
  }}>
   <div className="form-fields">
    <p>请选择至少一项资料。需求和文件均可多选，也可以混合使用。</p>
    <details open><summary>业务需求（已选 {requirementIds.length} 项）</summary>
     <div className="document-choices"><SearchBox value={search} onChange={setSearch} placeholder="搜索需求编号或名称"/>
      {requirementsError&&<p className="form-error">{requirementsError.message}</p>}
      {!shown.length&&!requirementsError&&<p className="muted">没有可选的匹配需求</p>}
      {shown.map(requirement=><label className="checkbox-label" key={requirement.id}>
       <input type="checkbox" checked={requirementIds.includes(requirement.id)} onChange={event=>setRequirementIds(current=>
        event.target.checked?[...current,requirement.id]:current.filter(id=>id!==requirement.id))}/>
       {requirementLabel(requirement)}
      </label>)}
     </div>
    </details>
    <details open><summary>文件版本（已选 {sourceIds.length} 份）</summary>
     <div className="file-source-field"><button type="button" className="secondary" disabled={!bases.length} onClick={()=>setUpload(true)}>上传新文件</button>
      <DocumentChoices documents={documents} value={sourceIds} onChange={setSourceIds}/>
     </div>
    </details>
    {!isMindMap&&<label>汇报对象（可选）<input value={audience} onChange={event=>setAudience(event.target.value)} maxLength={200} placeholder="例如项目例会、管理层评审"/></label>}
    <label>{isMindMap?'梳理范围或重点（可选）':'汇报目的或重点（可选）'}<textarea rows={3} value={task} onChange={event=>setTask(event.target.value)} maxLength={20000}
     placeholder={isMindMap?'例如梳理审批规则、各角色的职责及待确认事项':'例如说明本批需求的交付范围、主要依赖和需要确认的事项'}/></label>
   </div>
   <footer><button type="button" className="secondary" onClick={close}>取消</button>
    <button className="primary" disabled={empty||busy}><Play size={15}/>{busy?'创建中…':isMindMap?'生成思维导图':'生成一页 PPT'}</button>
   </footer>
  </form>
 </Modal>{upload&&<UploadModal bases={bases} defaultBase={bases[0].id} includeSourceFiles close={()=>setUpload(false)}/>}</>;
}
