import json, logging, sqlite3
from typing import Literal, TypedDict
from pydantic import BaseModel, Field, ValidationError
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import select
from ..models import AgentRun, AgentStep, SkillVersion, ModelConfig, User, DocumentVersion, Question,Requirement
from ..db import SessionLocal
from ..config import settings
from ..security import require_version,digest,write_lock
from .ai import complete, SYSTEM_POLICY
from .search import search
from .outlines import normalize_outline
from .deletion import active_filter,ensure_active
from .manuscript import strip_citation_ids,section_body
from .processing_tasks import linked_id
from .delivery import contract,quality


class Analysis(BaseModel):
    items: list[dict] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    answer: str = ''
    citations: list[str] = Field(default_factory=list)


CandidateField = Literal['questions', 'relations']


class AnalysisFormatError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__('模型返回的分析格式不符合要求，请重试任务。')
        self.reason = reason


def parse_analysis(text: str, candidate_field: CandidateField | None = None) -> dict:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise AnalysisFormatError(type(error).__name__) from None
    if candidate_field and payload == []:
        # Models sometimes return only the empty candidate list.
        payload = {candidate_field: []}
    try:
        return Analysis.model_validate(payload).model_dump()
    except ValidationError as error:
        raise AnalysisFormatError(error.errors(include_input=False)[0]['type']) from None


class State(TypedDict, total=False):
    run_id: str
    workflow: str
    evidence: list[dict]
    analysis: dict
    clarification: dict
    impact: dict
    outline: list[str]
    sections: list[dict]
    review: dict
    confirmed: bool
    ledger_preview: dict
    uml: dict
    ppt_report: dict
    mind_map: dict
    retrieval_meta: dict
    evidence_signature: str
    reused_from: dict


def step(run_id: str,agent: str,summary: str,output: dict):
    with SessionLocal() as db:
        db.add(AgentStep(run_id=run_id,agent=agent,summary=summary,output=output))
        db.commit()


def context(state: State):
    with SessionLocal() as db:
        run=db.get(AgentRun,state['run_id'])
        skill=db.get(SkillVersion,run.skill_version_id)
        model=db.get(ModelConfig,run.model_trace['model_config_id']) if run.model_trace.get('model_config_id') else None
        if not model or not model.enabled:
            from .ai import model_config
            model=model_config(db)
        return run.inputs,skill.config,run.owner_id,model.id


def ask(state: State,agent: str,instruction: str, *, candidate_field: CandidateField | None = None) -> dict:
    inputs,config,owner,model_id=context(state)
    write_section = agent=='Document Agent' and 'sections' in state
    if (inputs.get('_initialization_task')=='specification' or inputs.get('_initialization')) and write_section:
        instruction+='在受影响的功能或验收条目处把澄清候选中的未决事项明确标记为“待确认”。'
    if inputs.get('_specification_baseline_id'):
        instruction+=' 以 specification_baseline 作为现有软需，以 change_request 和任务中的变更说明为本次变更依据。仅修改受影响内容，保留其他规则与验收标准。'
        if inputs.get('_specification_primary_change_id'):
            instruction+=' 以 primary_change_request 标记的新版需求说明书为主要变更依据，change_request 为补充材料。'
    with SessionLocal() as db:
        srs_policy=('\n本次交付为完整软件需求说明书，不能用候选需求摘要代替。以任务 target_system 为适用系统。证据中 role=writing_sample 的内容仅参考结构、表达深度和写法，不能作为本次业务事实或复制接口编号。默认章节为文档基本信息、需求背景与目标、整体业务方案概述、核心功能需求、验收标准；尊重技能指定结构。功能按适用性写清改造位置、角色、触发条件、字段、处理逻辑、异常及系统边界；验收与功能对应。未知日期边界、接口和金融规则标为待确认，不自行确定。' if config['workflow']=='specification' else '')
        quality_id=inputs.get('_quality_version_id')
        delivery=contract(config) if config['workflow'] in ('specification','quality') else None
        if quality_id:
            delivery=require_version(db,quality_id,db.get(User,owner)).provenance.get('delivery_template') or delivery
        delivery_policy=('\n交付契约：'+json.dumps(delivery,ensure_ascii=False)) if delivery else ''
        format_hint = '返回一个 JSON 对象。items/questions/relations 均为对象数组，outline/citations 为字符串数组，answer 为字符串。只返回本次职责的字段。'
        if candidate_field:
            instruction += '\n若没有候选，请返回 ' + json.dumps({candidate_field: []}) + '。'
        if write_section:
            format_hint += ' 当前步骤只返回 {"answer":"本章节正文","citations":[]} 这种结构。answer 必须包含正文，Markdown 写在 answer 字符串内。'
        from .qa import skill_references
        messages = [
            {'role':'system','content':SYSTEM_POLICY+'\n'+config['system_prompt']+srs_policy+delivery_policy+'\n'+format_hint},
            {'role':'user','content':json.dumps({
                'task':config.get('user_template','{task}').replace('{task}',inputs['task']),
                'target_system':inputs.get('target_system',''),'instruction':instruction,
                'skill_references':skill_references(config),'evidence_untrusted':state.get('evidence',[]),
                'prior':{k:v for k,v in state.items() if k not in ('evidence','run_id')},
            },ensure_ascii=False)},
        ]
        model = db.get(ModelConfig,model_id)
        for attempt in range(2):
            text,trace=complete(db,owner,messages,json_output=True,config=model,
                                temperature=config.get('model_parameters', {}).get('temperature', 0.2),read_timeout=None)
            try:
                parsed=parse_analysis(text,candidate_field)
                if write_section and not parsed['answer'].strip():
                    raise AnalysisFormatError('empty_answer')
                break
            except AnalysisFormatError as error:
                logging.warning('Invalid model output for %s (%s): %s',state['run_id'],agent,error.reason)
                if attempt:
                    raise
                messages.append({'role':'user','content':'请重新完成原任务。上次返回的结构不符合要求。'
                                 + format_hint + ' JSON 对象外不要添加其他文字或代码块。'})
        allowed={c['citation_id'] for c in state.get('evidence',[]) if c.get('role')!='writing_sample'}
        if set(parsed['citations'])-allowed:
            raise RuntimeError('模型引用了不存在的来源，质量校验失败')
        for field in ('items','questions','relations'):
            if any(item.get('source_citation_id') and item['source_citation_id'] not in allowed for item in parsed[field]):
                raise RuntimeError('模型候选引用了不存在的来源，质量校验失败')
        db.commit()
    step(state['run_id'],agent,'模型完成结构化候选分析',{'result':parsed,'model_trace':trace})
    return parsed


def supervisor(state: State) -> dict:
    _,config,_,_=context(state)
    from .ledger_fill import workflow
    selected=workflow(config)
    step(state['run_id'],'Supervisor Agent','已选择技能工作流',{'workflow':selected})
    return {'workflow':selected}


def ledger_fill(state: State) -> dict:
    from .ledger_fill import prepare,finish,instruction
    with SessionLocal() as db:
        run=db.get(AgentRun,state['run_id']);preview=prepare(db,run)
        config=db.get(SkillVersion,run.skill_version_id).config
    evidence=list(state.get('evidence',[]))
    meta=config.get('package_metadata',{})
    if meta.get('file_hash'):
        from .files import blob
        from .skill_packages import package_files
        original=blob(meta['file_hash'])
        if original.exists() and str(meta.get('filename','')).lower().endswith(('.zip','.skill')):
            for name,data in package_files(original.read_bytes()).items():
                if name.endswith(('/references/field-mapping.md','/references/classification.md')):
                    evidence.append({'citation_id':'ledger-rule:'+name,'role':'ledger_rules','excerpt':data.decode('utf-8-sig')[:40000],'title':name})
    result=ask({**state,'evidence':evidence},'Ledger Fill Agent',instruction(preview))
    return {'ledger_preview':finish(preview,result)}


def uml(state: State) -> dict:
    from .uml import generate
    result=generate(state['run_id'],*context(state))
    step(state['run_id'],'UML Agent',f"已处理 {len(result['diagrams'])} 种 UML 图",{'diagram_types':[d['diagram_type'] for d in result['diagrams']]})
    return {'uml':result}


def ppt_report(state: State) -> dict:
    from .ppt_report import generate
    result=generate(*context(state))
    step(state['run_id'],'PPT Report Agent','已生成一页可编辑汇报 PPT',{'source_count':len(result['sources'])})
    return {'ppt_report':result}


def mind_map(state: State) -> dict:
    from .mind_map import generate
    result=generate(*context(state))
    step(state['run_id'],'Mind Map Agent','已整理思维导图',{'node_count':result['node_count'],'source_count':len(result['sources'])})
    return {'mind_map':result}


def knowledge(state: State) -> dict:
    inputs,config,owner,_=context(state)
    with SessionLocal() as db:
        user=db.get(User,owner)
        from .qa import collect
        from ..schemas import ChatInput
        evidence,meta=collect(db,user,ChatInput(content=inputs['task'],qa_mode='analysis',scopes=['formal','mine','selected'],version_ids=inputs.get('source_version_ids',[])),[],base_ids=inputs.get('base_ids') or config.get('base_ids'),can_search='search' in config['allowed_tools'],can_read='read_source' in config['allowed_tools'],include_task_records=False)
        # Use the same authorized retrieval engine as Chat. Explicit Work input retains
        # full bounded text because generation needs coverage beyond a query's top hits.
        evidence=[c for c in evidence if c.get('document_version_id') not in inputs.get('source_version_ids',[]) and c.get('record_kind')!='agent_run']
        evidence=[entry for entry in evidence if entry.get('document_version_id') not in inputs.get('sample_version_ids',[])]
        if 'read_source' in config['allowed_tools']:
            explicit_ids=inputs.get('source_version_ids',[])
            budget=min(60000,120000//max(1,len(explicit_ids))) if inputs.get('_requirement_pack_id') else 60000
            for vid in explicit_ids:
                version=require_version(db,vid,user)
                if inputs.get('_requirement_pack_id') or inputs.get('_initialization_task') or inputs.get('_initialization') or inputs.get('_quality_version_id'):
                    ensure_active(db,'document',version.document_id)
                # Explicit private inputs are labelled, never added to official retrieval index.
                entry={'citation_id':version.id,'document_version_id':version.id,'title':version.filename,'version':version.label,'locator':'显式输入全文','excerpt':version.content[:budget],'status':version.status,'current':False}
                if inputs.get('_quality_version_id'):
                    entry['role']='quality_target' if vid==inputs['_quality_version_id'] else 'quality_reference'
                if inputs.get('_specification_baseline_id'):
                    entry['role']='specification_baseline' if vid==inputs['_specification_baseline_id'] else 'change_request'
                    if vid==inputs.get('_specification_primary_change_id'):
                        entry['role']='primary_change_request'
                evidence.append(entry)
                if len(version.content)>budget:meta['warnings'].append(f'{version.filename} 超过全文上下文上限，仅采用前{budget}字，请分拆资料或核对遗漏。')
            for vid in inputs.get('sample_version_ids',[]):
                version=require_version(db,vid,user)
                evidence.append({'citation_id':'sample:'+version.id,'document_version_id':version.id,'title':version.filename,'version':version.label,'locator':'写作样例，仅供结构参考','role':'writing_sample','excerpt':version.content[:40000],'status':version.status,'current':False})
        requirement_id=linked_id(db,db.get(AgentRun,state['run_id']))
        if requirement_id:
            from .requirement_packs import run_pack_id
            pack_id=run_pack_id(requirement_id,inputs)
            for question in db.scalars(select(Question).where(active_filter('question',Question.id),Question.requirement_id==requirement_id,Question.owner_id==owner,Question.status=='confirmed')).all():
                question_pack=question.evidence.get('requirement_pack_id')
                if not question_pack and question.evidence.get('agent_run_id'):
                    origin=db.get(AgentRun,question.evidence['agent_run_id'])
                    question_pack=run_pack_id(requirement_id,origin.inputs) if origin else requirement_id
                if (question_pack or requirement_id) != pack_id:
                    continue
                evidence.append({'citation_id':question.id,'locator':'人工确认澄清','excerpt':question.conclusion,'status':'confirmed'})
        run=db.get(AgentRun,state['run_id'])
        run.citations=evidence
        evidence.sort(key=lambda c:c.get('citation_id') not in inputs.get('source_version_ids',[]))
        signature=digest(json.dumps({'evidence':evidence,'task':inputs['task'],'system':inputs.get('target_system'),'skill_version':run.skill_version_id,'requirement':requirement_id,'requirement_pack':inputs.get('_requirement_pack_id') or requirement_id,'requirement_revision':db.get(Requirement,requirement_id).revision if requirement_id else None},sort_keys=True,ensure_ascii=False))
        db.commit()
    step(state['run_id'],'Knowledge Agent',f'已保存 {len(evidence)} 条实际来源及版本',{'evidence':evidence,'retrieval_meta':meta,'retrieval_strategy':'shared-qa-v2'})
    return {'evidence':evidence,'retrieval_meta':meta,'evidence_signature':signature}

def analyze(state,field,agent,instruction, *, candidate_field: CandidateField | None = None):
    inputs,_,owner,_=context(state)
    if inputs.get('reuse_analysis',True) and inputs.get('requirement_id'):
        with SessionLocal() as db:
            current=db.get(AgentRun,state['run_id'])
            for previous in db.scalars(select(AgentRun).where(AgentRun.owner_id==owner,AgentRun.status=='completed',AgentRun.id!=current.id,active_filter('agent_run',AgentRun.id)).order_by(AgentRun.created_at.desc())).all():
                # Reuse only explicitly saved human-confirmed analysis, same evidence,
                # prompt version, task and current business identity.
                if linked_id(db,previous)==linked_id(db,current) and previous.result.get('evidence_signature')==state.get('evidence_signature') and previous.result.get('saved_'+field) and previous.result.get(field):
                    step(state['run_id'],agent,'复用同一来源版本下已人工确认的分析',{'from_run_id':previous.id,'field':field})
                    return {field:previous.result[field],'reused_from':{**state.get('reused_from',{}),field:previous.id}}
    return {field:ask(state,agent,instruction,candidate_field=candidate_field)}


def requirement(state: State) -> dict:
    return analyze(state,'analysis','Requirement Agent','逐条提取原子需求候选，记录 title/description/tags/source_citation_id。tags 使用分类到字符串列表的对象，例如 {"系统":["信贷系统"],"标签":["影像自动标记"]}，没有标签时用空对象。识别需求编号、适用系统与项目、当前行为和目标行为、参与角色、系统边界及待确认事项。相同编号的不同台账行保留，不擅自合并。不得补造金融规则。知识问答则在 answer 中给出带引用的回答。')


def clarification(state: State) -> dict:
    return analyze(state,'clarification','Clarification Agent','在 questions 中识别缺失、冲突和歧义，每条包含 description/category/reason/target/blocking/source_citation_id；区分阻塞生成和可稍后核实的问题，保留已有待确认事项。',candidate_field='questions')


def impact(state: State) -> dict:
    return analyze(state,'impact','Impact Agent','在 relations 中生成变更影响矩阵，每条记录 kind/description/system/function/flow/field/interface/evidence_kind/source_citation_id；区分有直接证据的事实与建议核实的推断；全部保持候选，不能自动确认为已批准规则。',candidate_field='relations')


def outline(state: State) -> dict:
    inputs,config,_,_=context(state)
    if inputs.get('fixed_template'):
        template=contract(config)
        if inputs.get('_specification_baseline_id'):
            with SessionLocal() as db:
                baseline=db.get(DocumentVersion,inputs['_specification_baseline_id'])
                if baseline:
                    template=baseline.provenance.get('delivery_template') or template
        titles=normalize_outline(template['outline'])
        step(state['run_id'],'Document Agent','采用已版本化的交付模板，直接生成正文',{'outline':titles,'template':template})
        return {'outline':titles,'confirmed':True}
    result=ask(state,'Document Agent','只在 outline 中返回软需章节提纲，严格遵循技能指令规定的文档结构、顺序和适用范围。仅在技能未指定结构时参考需求背景与目标、整体业务方案、核心功能需求、验收标准及待确认事项。')
    if not result['outline']:
        raise RuntimeError('未生成有效提纲')
    return {'outline':normalize_outline(result['outline'])}


def human(state: State) -> dict:
    confirmation=interrupt({'outline':state['outline'],'message':'请人工核对提纲和适用范围后确认'})
    if not isinstance(confirmation,dict) or confirmation.get('approved') is not True:
        raise RuntimeError('人工确认未通过')
    accepted=normalize_outline(confirmation.get('outline') if confirmation.get('outline') is not None else state['outline'])
    step(state['run_id'],'Human','用户已确认提纲',{'outline':accepted})
    return {'confirmed':True,'outline':accepted}


def document(state: State) -> dict:
    sections=[]
    titles=normalize_outline(state['outline'])
    for title in titles:
        result=ask({**state,'outline':titles,'sections':sections},'Document Agent',f'编写“{title}”章节，严格遵循技能指令要求的内容与文档格式。只写本标题直接所属的正文，不重复本章标题，不展开提纲中将单独生成的其他章节或子章节；父章节没有独立内容时仅写简短概述。正文放在 answer 中，来源ID仅放在 citations 数组，正文禁止输出 [citation_id:...]、UUID 等内部引用标记。保留验收标准和未确认事项，不能把推断当事实。不要把执行过程或质量检查报告混入正文。')
        if not result['answer'].strip():
            raise RuntimeError('模型返回空章节')
        sections.append({'title':title,'content':section_body(title,result['answer'],titles),'citations':result['citations']})
    return {'sections':sections}


def review(state: State) -> dict:
    inputs,config,owner,_=context(state)
    target_id=inputs.get('_quality_version_id')
    instruction='检查需求覆盖、章节一致性、证据与待确认事项；在 items 中逐项列出来源需求到正文的覆盖矩阵（requirement/section/status，其中 status 为 covered、missing 或 uncertain），核对每个功能是否有验收点，列出缺失和待确认项。在 answer 中给出质量检查报告。不要用样例的业务内容补齐事实。此检查不等于正式人工审批。'
    if target_id:
        instruction+='只检查 role=quality_target 标记的所选软需版本正文。role=quality_reference 是核对需求覆盖的来源，不能作为受检正文。若正文超出上下文上限，请在报告标注核查范围。'
    result=ask(state,'Review Agent',instruction)
    from .manuscript import assemble_sections
    if target_id:
        with SessionLocal() as db:
            target=require_version(db,target_id,db.get(User,owner))
            result['structure_check']=quality(target.content,target.provenance.get('delivery_template') or contract(config))
    elif state['workflow'] in ('specification','quality'):
        result['structure_check']=quality(assemble_sections(state.get('sections',[])) or '\n'.join(e.get('excerpt','') for e in state.get('evidence',[]) if e.get('locator')=='显式输入全文'),contract(config))
    return {'review':result}


def build_graph(checkpointer):
    graph=StateGraph(State)
    for name,node in [('supervisor',supervisor),('knowledge',knowledge),('ledger_fill',ledger_fill),('requirement',requirement),('clarification',clarification),('impact',impact),('outline',outline),('human',human),('document',document),('review',review)]:
        graph.add_node(name,node)
    graph.add_edge(START,'supervisor')
    graph.add_node('uml',uml)
    graph.add_node('ppt_report',ppt_report)
    graph.add_node('mind_map',mind_map)
    graph.add_conditional_edges('supervisor',lambda state:state['workflow'] if state['workflow'] in ('uml','ppt_report','mind_map') else 'knowledge')
    graph.add_edge('uml',END)
    graph.add_edge('ppt_report',END)
    graph.add_edge('mind_map',END)
    def after_knowledge(state):
        if state['workflow']=='ledger_fill':
            return 'ledger_fill'
        if state['workflow']=='quality' and any(e.get('role')=='quality_target' for e in state.get('evidence',[])):
            return 'review'
        return 'requirement'
    graph.add_conditional_edges('knowledge',after_knowledge)
    graph.add_edge('ledger_fill',END)
    graph.add_conditional_edges('requirement',lambda s: {'qa':'review','analysis':'review','quality':'review','clarification':'clarification','impact':'impact','specification':'clarification'}[s['workflow']])
    graph.add_conditional_edges('clarification',lambda s:'impact' if s['workflow']=='specification' else 'review')
    graph.add_conditional_edges('impact',lambda s:'outline' if s['workflow']=='specification' else 'review')
    graph.add_conditional_edges('outline',lambda state:'human' if not state.get('confirmed') and context(state)[1].get('human_confirmation',True) else 'document')
    graph.add_edge('human','document')
    graph.add_edge('document','review')
    graph.add_edge('review',END)
    return graph.compile(checkpointer=checkpointer)


def execute(run_id: str):
    with SessionLocal() as db:
        run=db.get(AgentRun,run_id)
        if run.status in ('completed','awaiting_confirmation'):
            return
        resume=run.inputs.get('_resume')
        track_progress=bool(run.inputs.get('_initialization'))
        run.status='running'
        local_change=run.inputs.get('_specification_change_mode')=='partial'
        db.commit()
    if local_change:
        from .specification_revision import plan_local_change
        plan_local_change(run_id)
        return
    connection=sqlite3.connect(str(settings.storage_dir/'agent-checkpoints.db'),check_same_thread=False,timeout=30)
    try:
        graph=build_graph(SqliteSaver(connection))
        config={'configurable':{'thread_id':run_id}}
        prior=graph.get_state(config)
        interrupted=any(task.interrupts for task in prior.tasks)
        graph_input=Command(resume=resume) if resume and interrupted else None if prior.values else {'run_id':run_id}
        if track_progress:
            completed=set()
            for values in graph.stream(graph_input,config,stream_mode='values',durability='sync'):
                ready={key for key in ('analysis','clarification','impact') if key in values}
                if ready-completed:
                    with SessionLocal() as db:
                        write_lock(db)
                        run=db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update())
                        run.result={**run.result,**{key:values[key] for key in ready}}
                        db.commit()
                    completed=ready
            snapshot=graph.get_state(config)
            result=snapshot.values
            paused=any(task.interrupts for task in snapshot.tasks)
        else:
            result=graph.invoke(graph_input,config)
            paused=bool(result.get('__interrupt__'))
        serial={k:v for k,v in result.items() if k!='__interrupt__'}
        with SessionLocal() as db:
            write_lock(db)
            run=db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update())
            saved={key:value for key,value in run.result.items() if key.startswith('saved_')}
            run.result={**serial,**saved}
            run.status='awaiting_confirmation' if paused else 'completed'
            db.commit()
    finally:
        connection.close()
