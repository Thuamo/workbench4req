"""One-time release polish, using exact guarded replacements."""
from pathlib import Path

def replace(path,old,new):
    file=Path(path)
    text=file.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'Expected source missing: {path}')
    file.write_text(text.replace(old,new,1),encoding='utf-8')

replace('frontend/components/knowledge.tsx','<div className="knowledge-layout">','<div className="mobile-base-selector"><label>知识库<select value={effectiveBase} onChange={e=>{setBaseId(e.target.value);setFolderId(\'\');}}>{bases.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select></label><label>目录<select value={folderId} onChange={e=>setFolderId(e.target.value)}><option value="">全部文件</option>{folders.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label></div><div className="knowledge-layout">')
replace('frontend/lib/types.ts','export type Message = {id:string;','export type Message = {generation_status:string;id:string;')
replace('frontend/components/chat.tsx','<small>{date(m.created_at)}</small></div>','<small>{date(m.created_at)}</small>{m.generation_status===\'stopped\'&&<span className="badge">已停止 · 部分内容</span>}{m.generation_status===\'failed\'&&<span className="badge returned">生成失败 · 部分内容</span>}</div>')
replace('frontend/components/ui.tsx',"catch(error) {setToast", "catch(error) {if(error instanceof Error&&error.name==='AbortError'){await query.invalidateQueries();setToast({text:'已停止生成',error:false});return undefined;}setToast")
replace('frontend/components/chat.tsx','abort.current?.abort();setBusy(false);','abort.current?.abort();')
replace('frontend/components/chat.tsx',"const [selectedRequirements,setSelectedRequirements]=useState<number[]>([]);", "const [selectedRequirements,setSelectedRequirements]=useState<number[]>([]);const [selectedRelations,setSelectedRelations]=useState<number[]>([]);const [targetRequirement,setTargetRequirement]=useState('');")
replace('frontend/components/chat.tsx'," const questions=clarification.questions||[];", " const {data:relatedRequirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});\n const relations=((run.result.impact||{}) as {relations?:Record<string,Json>[]}).relations||[];\n const questions=clarification.questions||[];")
# Hooks must precede early loading returns.
file=Path('frontend/components/chat.tsx')
text=file.read_text(encoding='utf-8')
hook=" const {data:relatedRequirements=[]}=useQuery({queryKey:['requirements'],queryFn:()=>api<Requirement[]>('/requirements')});\n"
text=text.replace(hook,'',1).replace(' if(isLoading)return <Loading/>;',hook+' if(isLoading)return <Loading/>;',1)
file.write_text(text,encoding='utf-8')
replace('frontend/components/chat.tsx','{sections.map((s,i)=>', '''{relations.length>0&&<section className="candidate-list"><h3>影响关联候选</h3>{relations.map((relation,i)=><label className="candidate-item" key={i}><input type="checkbox" checked={selectedRelations.includes(i)} onChange={e=>setSelectedRelations(e.target.checked?[...selectedRelations,i]:selectedRelations.filter(x=>x!==i))}/><JsonView value={relation}/></label>)}{run.inputs.requirement_id?<><label>人工选择关联目标<select value={targetRequirement} onChange={e=>setTargetRequirement(e.target.value)}><option value="">请选择目标需求</option>{relatedRequirements.filter(r=>r.id!==run.inputs.requirement_id).map(r=><option key={r.id} value={r.id}>{r.number} {r.title}</option>)}</select></label><button className="secondary" disabled={!selectedRelations.length||!targetRequirement} onClick={()=>void perform(()=>api('/agent-runs/'+run.id+'/save-relations','POST',{selected_indices:selectedRelations,target_id:targetRequirement}),'已保存关联候选，请在需求关联页确认')}>保存为关联候选</button></>:<p className="notice">运行时关联具体需求后，可将影响候选保存到需求关系图。</p>}</section>}{sections.map((s,i)=>''')
with Path('frontend/app/globals.css').open('a',encoding='utf-8') as css:
    css.write('\n.mobile-base-selector{display:none}\n@media(max-width:900px){.mobile-base-selector{display:flex;gap:12px;margin-bottom:16px}.mobile-base-selector label{flex:1;font-size:11px;color:var(--muted)}.mobile-base-selector select{display:block;margin-top:6px;width:100%}}\n')
print('Release UI polish applied')
