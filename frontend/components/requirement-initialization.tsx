'use client';

import {useRef, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api,date} from '../lib/api';
import type {Base,ProcessingTask} from '../lib/types';
import type {PageKey} from './workbench';
import {DeleteRecordButton} from './delete-record-button';
import {AssociatePackDocuments} from './pack-document-association';
import {Modal, SearchBox, SearchSelect, useAction} from './ui';
import {canReviewCandidates,hasCandidates} from './task-candidates';
type Source = {id: string; title: string; filename?:string; label: string; parse_status: string; error: string | null; can_retry: boolean};
const MAX_TASK_DOCUMENTS=10;
export type Initialization = {sources: Source[]; suggested_source_id: string | null; target_system: string;
  quality_versions?: Source[];
  baseline_versions?: Source[];
  consolidation_sources?: Source[];
  skills: {id: string; name: string; human_confirmation: boolean}[]; missing: string[];
  extra_skills?: {id: string; name: string; description: string; workflow: string; human_confirmation: boolean}[]};
const taskLabels: Record<string, string> = {
  clarification: '需求缺口识别',
  impact: '变更影响分析',
  specification: '生成软需草稿',
  ledger_fill: '澄清台账自动填报',
};
const taskOrder = Object.keys(taskLabels);
export const packStageLabels={clarification:'澄清阶段',specification:'软需阶段',consolidation:'沉淀阶段'};
export type PackStage = keyof typeof packStageLabels;
const packStages=Object.keys(packStageLabels) as PackStage[];
type PackScope = {id:string;stage:PackStage;label:string;canChange:boolean};
const changeModes={
 manual:{label:'手动改版',detail:'复制基线，在编辑器中直接修改',action:'创建草稿并编辑'},
 partial:{label:'局部变更',detail:'生成逐条建议，核对后应用',action:'生成变更建议'},
 full:{label:'整版重编',detail:'依据完整的新版需求说明书生成整版',action:'生成整版草稿'},
};
type ChangeMode=keyof typeof changeModes;
function skillStage(workflow:string):PackStage {
  if(['specification','quality','uml'].includes(workflow))return 'specification';
  if(['ppt_report','mind_map'].includes(workflow))return 'consolidation';
  return 'clarification';
}

function taskRank(workflow: string) {
  const index = taskOrder.indexOf(workflow);
  return index < 0 ? taskOrder.length : index;
}

export function RequirementTaskActions({id, plan, bases, scope, navigate}: {
  id: string; plan: Initialization; bases: Base[]; scope:PackScope; navigate:(page:PageKey,id?:string)=>void;
}) {
  const [open,setOpen] = useState(false);
  return <>
    <button className="primary" onClick={() => setOpen(true)}>发起任务</button>
    {open && <TaskLaunchWizard id={id} plan={plan} scope={scope} bases={bases} navigate={navigate} close={() => setOpen(false)}/>}
  </>;
}

function TaskLaunchWizard({id, plan, scope, bases, navigate, close}: {
  id: string; plan: Initialization; scope:PackScope; bases:Base[]; navigate:(page:PageKey,id?:string)=>void; close: () => void;
}) {
  const {perform} = useAction();
  const [step,setStep] = useState<'selection'|'settings'>('selection');
  const [basic,setBasic] = useState<string[]>([]);
  const [extras,setExtras] = useState<string[]>([]);
  const [diagramTypes,setDiagramTypes] = useState<string[]>([]);
  const [requestId] = useState(() => crypto.randomUUID());
  const [busy,setBusy] = useState(false);
  const [change,setChange] = useState(false);
  const [changeMode,setChangeMode] = useState<ChangeMode>('partial');
  const [changeSection,setChangeSection] = useState('');
  const [primaryChangeId,setPrimaryChangeId] = useState('');
  const [baselineId,setBaselineId] = useState('');
  const [changeNote,setChangeNote] = useState('');
  const [sourceIds,setSourceIds] = useState<string[]>([]);
  const [associating,setAssociating] = useState<PackStage|null>(null);
  const running = useRef(false);
  const qualityVersions = plan.quality_versions || [];
  const baselines = plan.baseline_versions || [];
  const baseline = baselines.find(v=>v.id===baselineId) || baselines[0];
  const [options,setOptions] = useState({
    target_system: plan.target_system,
    skill_id: plan.skills[0]?.id || '', fixed_template: true, quality_version_id: qualityVersions[0]?.id || '',
  });
  const extraSkills = plan.extra_skills || [];
  const selectedBasic = taskOrder.filter(kind => plan.missing.includes(kind)&&basic.includes(kind));
  const selectedExtras = extraSkills.filter(skill => extras.includes(skill.id));
  const count = Number(change) + selectedBasic.length + selectedExtras.length;
  const allBasic = !!plan.missing.length && selectedBasic.length === plan.missing.length;
  const groups=packStages.map(stage=>({stage,basic:taskOrder.filter(kind=>skillStage(kind)===stage),
    extras:extraSkills.filter(skill=>skillStage(skill.workflow)===stage)}));
  const selectedStages=groups.filter(group=>group.basic.some(kind=>selectedBasic.includes(kind))
    ||group.extras.some(skill=>extras.includes(skill.id))||(change&&group.stage==='specification')).map(group=>group.stage);
  const consolidation=selectedStages.includes('consolidation');
  const associationStage=consolidation?'consolidation':selectedStages.find(stage=>stage===scope.stage)||selectedStages[0]||scope.stage;
  const sourceOptions=consolidation?plan.consolidation_sources||plan.sources:plan.sources;
  const regularIds=new Set(plan.sources.map(source=>source.id));
  const sharedSources=sourceIds.filter(id=>regularIds.has(id));
  const primaryOptions=plan.sources.filter(source=>sharedSources.includes(source.id)&&source.parse_status==='ready'&&source.id!==baseline?.id);
  const showSources=!change||changeMode!=='manual'||count>1;
  const singleChange=change&&count===1;
  const changeReady=!!baseline&&(changeMode==='manual'||(changeMode==='partial'
    ?!!changeNote.trim():primaryOptions.some(source=>source.id===primaryChangeId)));
  const basicDraft = selectedBasic.includes('specification');
  const needsSystem = basicDraft || selectedExtras.some(skill => skill.workflow === 'specification');
  const needsRegularSource = selectedBasic.length > 0 || selectedExtras.some(skill=>!['ppt_report','mind_map','quality'].includes(skill.workflow));
  const needsQualityVersion = selectedExtras.some(skill => skill.workflow === 'quality');
  const needsUml = selectedExtras.some(skill => skill.workflow === 'uml');
  const forceStandard = (basicDraft && plan.skills.find(skill => skill.id === options.skill_id)?.human_confirmation === false)
    || selectedExtras.some(skill => skill.workflow === 'specification' && !skill.human_confirmation);
  const {data:umlTypes=[],isLoading:loadingUml,error:umlError} = useQuery({
    queryKey:['uml-diagram-types'],
    queryFn:()=>api<{id:string;label:string}[]>('/uml/diagram-types'),
    enabled:step==='settings' && needsUml,
  });
  const duplicateSpec = basicDraft && selectedExtras.some(skill => skill.id === options.skill_id);
  const invalidInputs=showSources&&sourceIds.some(id=>!sourceOptions.some(source=>source.id===id&&source.parse_status==='ready'));
  const canStart=!!count&&!busy&&!invalidInputs&&(!change||changeReady)
    &&(!needsRegularSource||sharedSources.length>0)&&(!consolidation||sourceIds.length>0)
    &&(!needsSystem||!!options.target_system.trim())&&(!basicDraft||!!options.skill_id)&&!duplicateSpec
    &&(!needsUml||diagramTypes.length>0)&&(!needsQualityVersion||qualityVersions.some(version=>version.id===options.quality_version_id));

  async function start() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    try {
      const stages=groups.map(group=>({
        stage:group.stage,
        basic_tasks:group.basic.filter(kind=>selectedBasic.includes(kind)),
        skill_ids:group.extras.filter(skill=>extras.includes(skill.id)).map(skill=>skill.id),
        source_version_ids:group.stage==='consolidation'?sourceIds:sharedSources,
        target_system:options.target_system,
        skill_id:group.stage==='specification'&&basicDraft?options.skill_id:null,
        fixed_template:forceStandard||options.fixed_template,
        quality_version_id:group.stage==='specification'&&needsQualityVersion?options.quality_version_id:null,
        diagram_types:group.stage==='specification'&&needsUml?diagramTypes:[],
      })).filter(group=>group.basic_tasks.length||group.skill_ids.length);
      const result = await perform(() => api<{task_ids:Record<string,string>}>(`/requirements/${id}/packs/${scope.id}/launch-tasks`, 'POST', {
        request_id:requestId,stages,
        change:change?{mode:changeMode,baseline_version_id:baseline?.id,
          source_version_ids:changeMode==='manual'?[]:sharedSources,
          primary_change_version_id:changeMode==='full'?primaryChangeId:null,
          section:changeMode==='partial'?changeSection:'',change_note:changeNote,target_system:options.target_system}:null,
      }), singleChange&&changeMode==='manual'?'软需草稿已创建':'所选任务已提交');
      if (result) {
        close();
        const runId=result.task_ids.specification_change;
        if(runId)navigate(changeMode==='manual'?'editor':'task',changeMode==='manual'?'run~'+runId:runId);
      }
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  if(associating)return <AssociatePackDocuments requirementId={id}
    scope={{id:scope.id,stage:associating,label:scope.label+' / '+packStageLabels[associating]}} bases={bases}
    excludedIds={sourceIds} max={MAX_TASK_DOCUMENTS-sourceIds.length}
    onAssociated={ids=>setSourceIds(current=>[...new Set([...current,...ids])])}
    close={()=>setAssociating(null)}/>;
  return <Modal title={step==='selection'?'发起任务 · 选择任务':'发起任务 · 确认设置'} close={() => { if (!busy) close(); }}>
    <form className="task-launch-form" onSubmit={event => {
      event.preventDefault();
      if (!count) return;
      if (step==='selection') setStep('settings'); else if(canStart) void start();
    }}>
      <div className="form-fields">
        <p className="notice">{scope.label}</p>
        {step==='selection' ? <>
          <section className="task-launch-section">
            <div className="task-launch-heading">
              <h3>任务输入文件{sourceIds.length>0&&<small className="muted"> · 已选 {sourceIds.length} 个</small>}</h3>
              <div className="button-group">
                <button type="button" className="secondary" disabled={sourceIds.length>=MAX_TASK_DOCUMENTS}
                  onClick={()=>setAssociating(associationStage)}>关联 / 上传文件</button>
                <button type="button" className="text-button" disabled={!plan.missing.length}
                  onClick={()=>setBasic(allBasic?[]:plan.missing)}>{allBasic?'取消全选基础任务':'一键选择基础任务'}</button>
              </div>
            </div>
          </section>
          {groups.map(group=><section className="task-launch-section" key={group.stage} aria-label={packStageLabels[group.stage]}>
            <h3>{packStageLabels[group.stage]}</h3>
            {group.basic.map(kind => {
              const exists = !plan.missing.includes(kind);
              return <label className="checkbox-label task-launch-option" key={kind}>
                <input type="checkbox" checked={selectedBasic.includes(kind)} disabled={exists}
                  onChange={event => setBasic(current => event.target.checked ? [...current,kind] : current.filter(item => item!==kind))}/>
                <span>{taskLabels[kind]}</span>{exists && <small className="muted">已创建</small>}
              </label>;
            })}
            {group.stage==='specification'&&scope.canChange&&<label className="checkbox-label task-launch-option">
              <input type="checkbox" checked={change} onChange={event=>setChange(event.target.checked)}/>
              <span>软需变更<small className="block muted">基于本包软需版本和变更依据生成新版草稿</small></span>
            </label>}
            {group.extras.map(skill => <label className="checkbox-label task-launch-option" key={skill.id}>
              <input type="checkbox" aria-label={skill.name} checked={extras.includes(skill.id)}
                onChange={event => setExtras(current => event.target.checked ? [...current,skill.id] : current.filter(item => item!==skill.id))}/>
              <span>{skill.name}{skill.description && <small className="block muted">{skill.description}</small>}</span>
            </label>)}
            {!group.basic.length&&!group.extras.length&&<p className="muted">暂无可发起的任务。</p>}
          </section>)}
        </> : <>
          <p>本次提交 · {[...selectedBasic.map(kind => taskLabels[kind]), ...selectedExtras.map(skill => skill.name),
            ...(change?[changeModes[changeMode].label+'（'+changeModes[changeMode].action+'）']:[])].join('、')}</p>
          {change&&<>
            <fieldset className="change-mode-picker" disabled={busy}>
              <legend>变更方式</legend>
              <div className="change-mode-options">
                {(Object.keys(changeModes) as ChangeMode[]).map(mode=><label className="checkbox-label change-mode-option" key={mode}>
                  <input type="radio" name="specification-change-mode" checked={changeMode===mode} onChange={()=>setChangeMode(mode)}/>
                  <span><strong>{changeModes[mode].label}</strong><small className="muted">{changeModes[mode].detail}</small></span>
                </label>)}
              </div>
            </fieldset>
            <label>基线软需<SearchSelect aria-label="基线软需" value={baselineId} onChange={event=>setBaselineId(event.target.value)}>
              <option value="">{baselines[0] ? '默认使用本包最近已确认版本 · '+baselines[0].label : '暂无可用软需版本'}</option>
              {baselines.map(v=><option key={v.id} value={v.id}>{v.title} · {v.label}</option>)}
            </SearchSelect></label>
            {!baseline&&<p className="form-error">请先为当前需求包确认一个软需版本。</p>}
            {changeMode==='partial'&&<label>目标章节（可选）<input value={changeSection} maxLength={300}
              placeholder="可从基线目录复制完整章节标题" onChange={event=>setChangeSection(event.target.value)}/></label>}
            <label>{changeMode==='manual'?'改版备注（可选）':changeMode==='partial'?'变更说明':'补充说明（可选）'}
              <textarea maxLength={10000} rows={3} value={changeNote} required={changeMode==='partial'}
                placeholder={changeMode==='partial'?'例如：法人证件号改为选填，并更新校验和验收用例。':undefined}
                onChange={event=>setChangeNote(event.target.value)}/>
            </label>
          </>}
          {showSources&&<LinkedTaskDocuments sources={sourceOptions} value={sourceIds} onChange={setSourceIds} busy={busy}
            consolidationOnly={consolidation?sourceOptions.filter(source=>!regularIds.has(source.id)).map(source=>source.id):[]}
            label={needsRegularSource||consolidation||change&&changeMode==='full'?'任务输入文件':'任务输入文件（可选）'} associate={()=>setAssociating(associationStage)}/>}
          {needsRegularSource&&consolidation&&sourceIds.length>0&&!sharedSources.length&&<p className="form-error">请再选一份可用于澄清或软需阶段的文件。</p>}
          {change&&changeMode==='full'&&<label>新版需求说明书<SearchSelect aria-label="新版需求说明书"
            value={primaryOptions.some(source=>source.id===primaryChangeId)?primaryChangeId:''} required
            onChange={event=>setPrimaryChangeId(event.target.value)}>
            <option value="">请从已选文件中指定完整的新版需求说明书</option>
            {primaryOptions.map(source=><option key={source.id} value={source.id}>{source.title} · {source.label}</option>)}
          </SearchSelect></label>}
          {needsQualityVersion&&<label>待核查软需版本<SearchSelect aria-label="待核查软需版本" value={options.quality_version_id} required
            onChange={event=>setOptions({...options,quality_version_id:event.target.value})}>
            <option value="">请选择软需版本</option>
            {qualityVersions.map(version=><option key={version.id} value={version.id}>{version.title} · {version.label}</option>)}
          </SearchSelect>{!qualityVersions.length&&<small className="form-error">请先为当前需求保存可读取的软需版本。</small>}</label>}
          {needsSystem && <label>目标系统<input value={options.target_system} required maxLength={200}
            onChange={event => setOptions({...options,target_system:event.target.value})}/></label>}
          {basicDraft && <>
            <label>软需生成技能<SearchSelect value={options.skill_id} required onChange={event => setOptions({...options,skill_id:event.target.value,fixed_template:true})}>
              {plan.skills.map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
            </SearchSelect></label>
            {!plan.skills.length && <p className="form-error">请先启用支持读取业务资料的软需生成技能。</p>}
            {duplicateSpec && <p className="form-error">同一技能已在基础任务中选用，请更换技能或返回取消重复选择。</p>}
          </>}
          {needsSystem && <label className="checkbox-label"><input type="checkbox" checked={forceStandard || options.fixed_template}
            disabled={forceStandard} onChange={event => setOptions({...options,fixed_template:event.target.checked})}/>使用标准目录直接生成正文</label>}
          {needsUml && <fieldset>
            <legend>UML 图种（可多选）</legend>
            {loadingUml && <p role="status">正在加载图种…</p>}
            {umlError && <p className="form-error">{umlError.message}</p>}
            <div className="form-grid">{umlTypes.map(type => <label className="checkbox-label" key={type.id}>
              <input type="checkbox" checked={diagramTypes.includes(type.id)}
                onChange={event => setDiagramTypes(current => event.target.checked ? [...current,type.id] : current.filter(item => item!==type.id))}/>{type.label}
            </label>)}</div>
          </fieldset>}
        </>}
      </div>
      <footer>
        {step==='selection' ? <>
          <button type="button" className="secondary" onClick={close}>取消</button>
          <button className="primary" disabled={!count}>下一步{count>0 ? `（${count} 项）` : ''}</button>
        </> : <>
          <button type="button" className="secondary" disabled={busy} onClick={() => setStep('selection')}>上一步</button>
          <button className="primary" disabled={!canStart}>
            {busy?'提交中…':singleChange?changeModes[changeMode].action:change?'确认提交':'确认发起'}
          </button>
        </>}
      </footer>
    </form>
  </Modal>;
}

function LinkedTaskDocuments({sources,value,onChange,busy,label,associate,consolidationOnly}: {
  sources:Source[];value:string[];onChange:(ids:string[])=>void;busy:boolean;label:string;associate:()=>void;consolidationOnly:string[];
}) {
  const [query,setQuery]=useState('');
  const {perform}=useAction();
  const matched=sources.filter(source=>[source.title,source.filename,source.label]
    .some(text=>text?.toLowerCase().includes(query.trim().toLowerCase())));
  const missing=value.filter(id=>!sources.some(source=>source.id===id));
  return <section className="task-launch-section linked-task-documents">
    <div className="task-launch-heading">
      <h3>{label}</h3>
      <button type="button" className="text-button" disabled={busy||value.length>=MAX_TASK_DOCUMENTS}
        onClick={associate}>关联 / 上传文件</button>
    </div>
    <p className="muted small">从当前需求包选择已解析版本，已选 {value.length} / {MAX_TASK_DOCUMENTS}。</p>
    {missing.length>0&&<button type="button" className="text-button" disabled={busy}
      onClick={()=>onChange(value.filter(id=>!missing.includes(id)))}>清除 {missing.length} 个已不可用版本</button>}
    {sources.length>5&&<SearchBox value={query} onChange={setQuery} placeholder="搜索文档或版本"/>}
    <fieldset className="linked-task-document-list" aria-label={label} disabled={busy}>
      {matched.map(source=>{
        const checked=value.includes(source.id);
        const available=source.parse_status==='ready';
        return <div key={source.id}>
          <label className="checkbox-label task-launch-option">
            <input type="checkbox" checked={checked} disabled={!checked&&(!available||value.length>=MAX_TASK_DOCUMENTS)}
              onChange={event=>onChange(event.target.checked?[...value,source.id]:value.filter(id=>id!==source.id))}/>
            <span>{source.title} · {source.label}{consolidationOnly.includes(source.id)&&<small className="muted"> · 仅用于沉淀阶段</small>}{!available&&<small className="muted">
              {source.parse_status==='failed'?'解析失败':'待解析'}
            </small>}</span>
          </label>
          {checked&&source.parse_status==='failed'&&<div className="initialization-parse">
            {source.error&&<small className="block form-error">{source.error}</small>}
            {source.can_retry&&<button type="button" className="text-button"
              onClick={()=>void perform(()=>api(`/versions/${source.id}/retry-parse`,'POST'),'已重新安排解析')}>重试解析</button>}
          </div>}
        </div>;
      })}
      {!matched.length&&<p className="muted">{sources.length?'没有匹配的文档版本':'当前包暂无可选的关联文档。'}</p>}
    </fieldset>
  </section>;
}

export function RequirementTaskRows({runs, navigate, openResult, readOnly=false}: {
  runs: ProcessingTask[]; navigate: (page: PageKey, id?: string) => void; openResult?: (id: string) => void; readOnly?: boolean;
}) {
  const {perform} = useAction();
  const [retrying, setRetrying] = useState<string | null>(null);
  const sorted = [...runs].sort((a, b) => taskRank(a.requirement_skill_task ? '' : a.workflow) - taskRank(b.requirement_skill_task ? '' : b.workflow));

  async function retry(runId: string) {
    setRetrying(runId);
    try { await perform(() => api(`/agent-runs/${runId}/retry`, 'POST'), '已安排重试'); }
    finally { setRetrying(null); }
  }

  return <>{sorted.map(run => {
    const kind = run.workflow;
    const title = (!run.requirement_skill_task && taskLabels[kind]) || run.skill_name || String(run.inputs.task);
    const resultReady = canReviewCandidates(run) && (hasCandidates(run) || kind === 'quality' && run.status === 'completed');
    const detailLabel = readOnly ? '任务详情' : run.status === 'awaiting_confirmation' ? '确认提纲'
      : kind === 'ledger_fill' && run.status === 'completed' && !run.result.saved_ledger_task_id ? '查看台账预览' : '任务详情';
    return <div key={run.id} className="version-row initialization-step">
      <div><strong>{title}</strong>
        <small className="block muted">{run.stage_label} · {date(run.created_at)}</small>
        {run.error && <small className="block form-error">{run.error}</small>}
      </div>
      <div className="button-group">
        {!readOnly && run.status === 'failed' && <button className="secondary" disabled={retrying !== null} onClick={() => void retry(run.id)}>
          {retrying === run.id ? '正在重试…' : '重试任务'}
        </button>}
        {openResult && resultReady && <button className="text-button" onClick={() => openResult(run.id)}>查看结果</button>}
        {!readOnly && kind === 'specification' && run.status === 'completed' && <button className="text-button" onClick={() => navigate('editor', `run~${run.id}`)}>编辑软需</button>}
        <button className="secondary" onClick={() => navigate('task', run.id)}>{detailLabel}</button>
        {!readOnly && !run.read_only && <DeleteRecordButton kind="agent_run" id={run.id} title={title}
          disabledReason={run.status === 'running' ? '任务执行中，结束后可删除' : undefined}/>}
      </div>
    </div>;
  })}</>;
}

