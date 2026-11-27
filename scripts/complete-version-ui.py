"""Apply guarded UI additions for document metadata and dependency lineage."""
from pathlib import Path
def replace(path,old,new):
    file=Path(path)
    text=file.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'Expected source missing: {path}')
    file.write_text(text.replace(old,new,1),encoding='utf-8')

replace('frontend/components/knowledge.tsx','Snapshot, ReviewTask','Snapshot, ReviewTask, Requirement')
replace('frontend/components/knowledge.tsx',"const [left,setLeft]=useState('');", "const [left,setLeft]=useState('');const [metadataForm,setMetadataForm]=useState(false);")
replace('frontend/components/knowledge.tsx'," const {data:version,isLoading}=useQuery", " const {data:document}=useQuery({queryKey:['document-metadata',documentId],queryFn:()=>api<Document>('/documents/'+documentId)});const {data:metadataFolders=[]}=useQuery({queryKey:['folders',document?.base_id],queryFn:()=>api<Folder[]>('/knowledge-bases/'+document?.base_id+'/folders'),enabled:!!document?.base_id});const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});const {data:impact}=useQuery({queryKey:['version-impact',documentId,versionId],queryFn:()=>api<unknown>(`/documents/${documentId}/impact?version_id=${versionId}`),enabled:tab==='impact'});\n const {data:version,isLoading}=useQuery")
replace('frontend/components/knowledge.tsx','<div className="document-actions">','<div className="document-actions">{document&&(document.owner_id===user.id||user.role===\'super_admin\')&&<button className="secondary" onClick={()=>setMetadataForm(true)}>名称、目录与关联</button>}')
replace('frontend/components/knowledge.tsx',"{key:'history',label:'操作记录'},", "{key:'history',label:'操作记录'},{key:'impact',label:'引用影响'},")
replace('frontend/components/knowledge.tsx',"{tab==='history'&&<JsonView value={history}/>}<", "{tab==='impact'&&<><p className=\"notice\">以下记录明确引用了当前所查看版本。是否需要变更，仍需人工核对。</p><JsonView value={impact}/></>}{tab==='history'&&<JsonView value={history}/>}<")
replace('frontend/components/knowledge.tsx','{revision&&<FormModal title="创建新修订"','''{metadataForm&&document&&<FormModal title="调整文档资产" initial={document} fields={[{key:'title',label:'资产名称',required:true},{key:'folder_id',label:'目录',type:'select',options:metadataFolders.map(f=>({value:f.id,label:f.name}))},{key:'requirement_id',label:'关联需求',type:'select',options:requirements.map(r=>({value:r.id,label:r.number+' '+r.title}))},{key:'kind',label:'资产类型',type:'select',options:[{value:'reference',label:'知识资料'},{value:'business',label:'业务原件'},{value:'specification',label:'软件需求'},{value:'template',label:'需求模板'}],required:true}]} close={()=>setMetadataForm(false)} onSubmit={v=>perform(()=>api('/documents/'+documentId,'PATCH',{...v,folder_id:v.folder_id||null,requirement_id:v.requirement_id||null}))}/>} {revision&&<FormModal title="创建新修订"''')
replace('frontend/components/business.tsx'," const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});const {data:relations", " const {data:lineage}=useQuery({queryKey:['lineage',selected?.id],queryFn:()=>api<unknown>('/requirements/'+selected?.id+'/lineage'),enabled:!!selected});const {data:requirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});const {data:relations")
replace('frontend/components/business.tsx',"title={selected.number+' · 度量记录'}", "title={selected.number+' · 度量与来源追溯'}")
replace('frontend/components/business.tsx','<div className="form-fields">{metrics.length?', '<div className="form-fields"><details><summary>业务原件、澄清、软需和执行版本闭环</summary><JsonView value={lineage}/></details>{metrics.length?')
print('Version metadata, reference impact and requirement lineage UI added')
