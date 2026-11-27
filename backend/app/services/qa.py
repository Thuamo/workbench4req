"""Permission-first evidence collection for the three Chat modes.

Private text indexes are bounded, content-addressed process caches. They never
update publication pointers; authorization is evaluated before every cache read.
"""
import difflib
import json
import math
import re
from collections import Counter
from functools import lru_cache
from fastapi import HTTPException
from sqlalchemy import select
from ..models import (DEVELOPMENT_MEMBER, Document, DocumentVersion, KnowledgeBase, Chunk, IndexBuild,
                      ModelConfig, Requirement, ClarificationTask, Relation, AgentRun,
                      ProcessingTaskContext, KnowledgeItem, KnowledgeRevision)
from ..config import settings
from ..security import base_allowed, require_version, digest
from .deletion import active_filter, requirement_filter, is_deleted
from .publishing import chunks_for
from .search import tokens
from .ai import embeddings

STOP=set('的 了 是 在 与 和 或 及 中 下 有 哪些 什么 如何 为什么 怎么 请 一下 内容 需求 大致 相关 进行 一个 是否 系统 业务'.split())
MODE_NAMES={'knowledge':'知识查询','compare':'跨文档及版本比较','analysis':'需求分析辅助'}
SCOPE_NAMES={'formal':'正式知识','mine':'我的已解析资料','selected':'所选文件'}


def terms(text):
    return [t for t in tokens(text) if t not in STOP and (len(t)>1 or t.isdigit())]


def numbers(text):
    # Five+ digit identifiers, including RM_00053002; short counts/dates are not IDs.
    return {str(int(x)) for x in re.findall(r'(?<!\d)(\d{5,})(?!\d)',text)}


def version_labels(text):
    return list(dict.fromkeys(re.findall(r'(?i)(?<![a-z0-9])V\s*(\d+(?:\.\d+)*)',text)))


def label_key(label):
    parts=label.lower().replace('v','').replace(' ','').split('.')
    while len(parts)>1 and parts[-1]=='0': parts.pop()
    return '.'.join(parts)


@lru_cache(maxsize=128)
def text_index(version_id, content_hash, serialized_blocks, content):
    from types import SimpleNamespace
    blocks=json.loads(serialized_blocks)
    if not blocks: blocks=[{'locator':'正文','text':content}]
    # Each paragraph carries its latest section path and table header.
    indexed=[];path=[];header=''
    table_headers={}
    for block in blocks:
        cell=re.match(r'(.*/ 表\d+)/R1C(\d+)$',block.get('locator',''))
        if cell: table_headers[(cell[1],cell[2])]=block.get('text','')
    for block in blocks:
        text=block.get('text','');kind=block.get('kind','')
        for line in text.splitlines():
            heading=re.match(r'^(#{1,6})\s+(.+)',line)
            if heading:
                level=len(heading[1]);path=path[:level-1]+[heading[2]]
        if kind=='table' or text.lstrip().startswith('|'):
            header='\n'.join(text.splitlines()[:2])
        else: header=''
        prefix=' / '.join(path)
        cell=re.match(r'(.*/ 表\d+)/R\d+C(\d+)$',block.get('locator',''))
        if cell and (cell[1],cell[2]) in table_headers:
            prefix+=' / 列：'+table_headers[(cell[1],cell[2])]
        for locator,excerpt in chunks_for(SimpleNamespace(blocks=[{'locator':block.get('locator','正文'),'text':text}])):
            indexed.append((locator, (prefix+'\n' if prefix else '')+(header+'\n' if header and not excerpt.startswith(header) else '')+excerpt))
    return tuple(indexed)


def version_chunks(db,doc,v,scope):
    chunks=text_index(v.id,digest(v.content),json.dumps(v.blocks,ensure_ascii=False,sort_keys=True),v.content)
    base=db.get(KnowledgeBase,doc.base_id)
    return [{'citation_id':f'{v.id}:{digest(locator+text)[:16]}','document_id':doc.id,
             'document_version_id':v.id,'title':doc.title,'filename':v.filename,
             'version':v.label,'locator':locator,'excerpt':text,'scope':scope,
             'status':v.status,'formal':v.publish_status=='published' and v.status in ('published','superseded'),
             'current':doc.current_version_id==v.id,'knowledge_base_id':doc.base_id,
             'base_name':base.name if base else '', 'content_hash':digest(v.content)} for locator,text in chunks]


def query_context(question,history):
    # Only same skill/mode/scope history reaches here. Do not make the LLM invent a query.
    previous=next((m.content for m in reversed(history) if m.role=='user'), '')
    followup=bool(re.match(r'^(那|那么|它|这个|上述|刚才|上一|与上一|还有|如果为空|为空时|其)',question)) or len(terms(question))<=1
    return (previous[-1200:]+'\n追问：'+question) if previous and followup else question


def skill_references(config):
    """Read bounded reference text from a validated skill archive; never run code."""
    meta=config.get('package_metadata',{})
    if not meta.get('file_hash') or not str(meta.get('filename','')).lower().endswith(('.zip','.skill')): return []
    from .files import blob
    from .skill_packages import package_files
    result=[];budget=24000
    for name,data in sorted(package_files(blob(meta['file_hash']).read_bytes()).items()):
        if ('/references/' not in '/'+name or not name.lower().endswith(('.md','.txt','.json'))) or not budget: continue
        text=data.decode('utf-8-sig')[:min(budget,8000)]
        result.append({'name':name,'text':text});budget-=len(text)
        if len(result)>=8: break
    return result


def allowed_versions(db,user,scopes,selected_ids,base_ids=None):
    bases={b.id for b in db.scalars(select(KnowledgeBase)).all() if base_allowed(b,user) and (not base_ids or b.id in base_ids)}
    docs={d.id:d for d in db.scalars(select(Document).where(active_filter('document',Document.id))).all()}
    result={}
    for v in db.scalars(select(DocumentVersion).order_by(DocumentVersion.created_at.desc())).all():
        doc=docs.get(v.document_id)
        if not doc or doc.base_id not in bases or v.parse_status!='ready': continue
        if 'formal' in scopes and doc.current_version_id==v.id and doc.current_index_id and v.status=='published' and v.publish_status=='published' and v.index_status=='ready':
            result[v.id]=(doc,v,'formal')
        elif 'mine' in scopes and v.creator_id==user.id and v.status not in ('deprecated','archived','superseded') and v.publish_status!='published':
            # Latest eligible personal revision per asset, not every draft in its history.
            if not any(d.id==doc.id for d,_,s in result.values() if s=='mine'):
                result[v.id]=(doc,v,'mine')
    if 'selected' in scopes:
        for vid in selected_ids:
            v=require_version(db,vid,user);doc=docs.get(v.document_id)
            if not doc: raise HTTPException(409,'所选文档已删除，请重新选择')
            if not base_allowed(db.get(KnowledgeBase,doc.base_id),user): raise HTTPException(404,'所选文件所属知识库不可用')
            if v.parse_status!='ready': raise HTTPException(409,'所选文件尚未解析完成')
            result[v.id]=(doc,v,'selected')
    return result


def number_candidates(rows,ids):
    if not ids: return rows
    exact=[r for r in rows if ids <= numbers(' '.join(str(r.get(k,'')) for k in ('title','filename')))]
    # Prefer identifier-bearing assets; unrelated assets mentioning that ID
    # in passing must not displace the requested requirement.
    return exact or [r for r in rows if not numbers(r.get('title','')+' '+r.get('filename','')) and ids<=numbers(r['excerpt'])]


def rank(rows,query,limit=14):
    query_terms=set(terms(query));ids=numbers(query)
    if not query_terms and not ids: return []
    rows=number_candidates(rows,ids)
    if not rows: return []
    counts=[Counter(terms(r.get('title','')+' '+r.get('locator','')+' '+r['excerpt'])) for r in rows]
    df={t:sum(t in c for c in counts) for t in query_terms};avg=sum(sum(c.values()) for c in counts)/len(rows) or 1
    ranked=[]
    for row,count in zip(rows,counts):
        matched=query_terms & count.keys()
        title_match=query_terms & set(terms(row.get('title','')+' '+row.get('locator','')))
        coverage=len(matched)/max(1,len(query_terms))
        # A single generic fragment cannot fill the top ten with unrelated documents.
        if not ids and not title_match and (not matched or coverage<settings.qa_min_token_coverage): continue
        score=sum(math.log(1+(len(rows)-df[t]+0.5)/(df[t]+0.5))*count[t]*2.2/(count[t]+1.2*(.25+.75*sum(count.values())/avg)) for t in matched)
        score+=2*len(title_match)+coverage+(5 if ids else 0)
        if score>0: ranked.append({**row,'score':round(score,4),'matched_terms':sorted(matched)})
    # Per-document diversity while retaining enough material for a selected file.
    output=[];per_doc=Counter()
    for row in sorted(ranked,key=lambda r:-r['score']):
        key=row.get('document_version_id') or row.get('record_id')
        if per_doc[key]>=5: continue
        per_doc[key]+=1;output.append(row)
        if len(output)>=limit: break
    return output


def records(db,user,query,include_runs=True):
    rows=[]
    def add(kind,obj,title,text,status,scope='mine'):
        rows.append({'citation_id':f'{kind}:{obj.id}:{getattr(obj,"revision",1)}','record_id':obj.id,
                     'record_kind':kind,'title':title,'locator':'业务登记记录（最多6000字符）','excerpt':text[:6000],
                     'scope':scope,'formal':False,'status':status})
    reqs=db.scalars(select(Requirement).where(Requirement.owner_id==user.id,requirement_filter())).all()
    for req in reqs: add('requirement',req,req.number+' '+req.title,req.description,req.state)
    if user.role==DEVELOPMENT_MEMBER:
        return rank(rows,query,6)
    for task in db.scalars(select(ClarificationTask).where(active_filter('clarification_task',ClarificationTask.id))).all():
        add('clarification_task',task,str(task.fields.get('需求编号',''))+' '+str(task.fields.get('需求名称','')),json.dumps(task.fields,ensure_ascii=False),task.status,scope='public_ledger')
    req_ids={r.id for r in reqs}
    for relation in db.scalars(select(Relation).where(Relation.owner_id==user.id,active_filter('relation',Relation.id))).all():
        if relation.source_id in req_ids and relation.target_id in req_ids:
            add('relation',relation,'需求关联 '+relation.kind,json.dumps({'source':next(r.number+' '+r.title for r in reqs if r.id==relation.source_id),'target':next(r.number+' '+r.title for r in reqs if r.id==relation.target_id),'evidence':relation.evidence},ensure_ascii=False),relation.status)
    for run in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id))).all() if include_runs else []:
        context=db.scalar(select(ProcessingTaskContext).where(ProcessingTaskContext.run_id==run.id))
        if context and context.requirement_id and context.requirement_id not in req_ids: continue
        add('agent_run',run,'处理任务 '+str(run.inputs.get('task',''))[:200],json.dumps({'task':run.inputs.get('task'),'requirement_id':context.requirement_id if context else None},ensure_ascii=False),run.status)
    return rank(rows,query,6)


def comparison(db,user,data,base_ids=None):
    explicit=list(dict.fromkeys(data.comparison_version_ids))
    if explicit:
        if len(explicit)!=2: raise HTTPException(422,'比较必须选择两个不同的文档版本')
        if 'selected' not in data.scopes: raise HTTPException(422,'请选择“所选文件”范围以比较指定文件')
        pool=allowed_versions(db,user,['selected'],explicit)
        chosen=[pool[i] for i in explicit]
    else:
        pool=allowed_versions(db,user,data.scopes,data.version_ids,base_ids)
        # Historical published versions are only eligible in explicit comparison mode.
        if 'formal' in data.scopes:
            for v in db.scalars(select(DocumentVersion).where(DocumentVersion.status=='superseded',DocumentVersion.publish_status=='published')).all():
                doc=db.get(Document,v.document_id)
                if not is_deleted(db,'document',doc.id) and base_allowed(db.get(KnowledgeBase,doc.base_id),user) and (not base_ids or doc.base_id in base_ids): pool[v.id]=(doc,v,'formal')
        ids=numbers(data.content);labels=version_labels(data.content)
        candidates=[x for x in pool.values() if ids and ids<=numbers(x[0].title+' '+x[1].filename+' '+x[1].content)]
        matches=[]
        for label in labels:
            group=[x for x in candidates if label_key(label) in {label_key(x[1].label),*[label_key(v) for v in version_labels(x[1].filename)]}]
            if len(group)!=1: break
            matches.append(group[0])
        if len(matches)!=2 or len(labels)!=2 or matches[0][1].id==matches[1][1].id:
            return [],{'notice':'请明确选择左、右两个文档版本；未找到唯一的指定版本，不会改用其他文件。','comparison_candidates':[{'id':v.id,'document_id':d.id,'title':d.title,'version':v.label,'filename':v.filename,'status':v.status} for d,v,_ in candidates[:30]]}
        chosen=matches
    evidence=[];segments=[];total_chars=0
    # Deterministic block diff first; the model explains these differences only.
    left,right=chosen
    def blocks(v): return v.blocks or [{'locator':'正文','text':v.content}]
    a,b=blocks(left[1]),blocks(right[1])
    opcodes=difflib.SequenceMatcher(a=[x.get('text','') for x in a],b=[x.get('text','') for x in b],autojunk=False).get_opcodes()
    total=sum(max(i2-i1,j2-j1) for tag,i1,i2,j1,j2 in opcodes if tag!='equal');covered=0
    for n,(tag,i1,i2,j1,j2) in enumerate(opcodes):
        if tag=='equal': continue
        # At most 120k characters per comparison. Report partial coverage explicitly.
        pieces=[]
        for side,(doc,v,scope),group in [('left',left,a[i1:i2]),('right',right,b[j1:j2])]:
            for k,block in enumerate(group):
                excerpt=block.get('text','')
                if total_chars+len(excerpt)>120000: continue
                total_chars+=len(excerpt)
                cid=f'{v.id}:diff:{n}:{k}'
                row={'citation_id':cid,'document_id':doc.id,'document_version_id':v.id,'title':doc.title,'version':v.label,'locator':block.get('locator','正文'),'excerpt':excerpt,'scope':scope,'status':v.status,'formal':v.publish_status=='published','side':side,'change':tag}
                evidence.append(row);pieces.append(cid)
        expected=(i2-i1)+(j2-j1)
        if len(pieces)==expected: covered+=max(i2-i1,j2-j1)
        segments.append({'change':tag,'evidence_ids':pieces,'complete':len(pieces)==expected})
    return evidence,{'comparison_versions':[{'id':v.id,'title':d.title,'version':v.label,'filename':v.filename,'status':v.status} for d,v,_ in chosen],
                     'comparison_changes':segments,'coverage':{'changed_blocks':total,'covered_blocks':covered,'complete':covered==total},
                     'notice':'两份文档正文相同，未检测到文本变化。' if not total else '比较内容超出本次上限，仅覆盖列出的变化块；请拆分文件后继续核对。' if covered!=total else ''}


def collect(db,user,data,history,base_ids=None,can_search=True,can_read=True,include_task_records=True):
    meta={'qa_mode':data.qa_mode,'scopes':list(dict.fromkeys(data.scopes)),'warnings':[]}
    if not data.scopes: raise HTTPException(422,'请至少选择一个检索范围')
    if (data.version_ids and 'selected' in data.scopes or data.comparison_version_ids) and not can_read: raise HTTPException(422,'当前技能未启用读取文件')
    if not can_search and any(s in data.scopes for s in ('formal','mine')):
        meta['warnings'].append('当前技能未启用知识检索，正式知识和我的资料未参与检索。')
    if data.qa_mode=='compare':
        if not can_read: raise HTTPException(422,'当前技能不支持读取比较文件')
        if not can_search and not data.comparison_version_ids: raise HTTPException(422,'当前技能不支持检索，请明确选择两个比较文件')
        evidence,detail=comparison(db,user,data,base_ids);return evidence,{**meta,**detail}
    query=query_context(data.content,history);meta['resolved_query']=query
    scopes=[s for s in data.scopes if can_search or s=='selected']
    versions=allowed_versions(db,user,scopes,data.version_ids,base_ids)
    rows=[];vectors={}
    for doc,v,scope in versions.values():
        if scope=='formal':
            build=db.get(IndexBuild,doc.current_index_id)
            if not build or build.status!='ready' or build.version_id!=v.id: continue
            for c in db.scalars(select(Chunk).where(Chunk.build_id==build.id)).all():
                rows.append({'citation_id':c.id,'document_id':doc.id,'document_version_id':v.id,'title':doc.title,'filename':v.filename,'version':v.label,'locator':c.locator,'excerpt':c.text,'scope':scope,'status':v.status,'formal':True,'current':True,'knowledge_base_id':doc.base_id})
                if c.embedding is not None: vectors[c.id]=(build.model_config_id,c.embedding)
        else: rows.extend(version_chunks(db,doc,v,scope))
    if can_search and 'formal' in scopes:
        bases={b.id for b in db.scalars(select(KnowledgeBase)).all() if base_allowed(b,user) and (not base_ids or b.id in base_ids)}
        for item in db.scalars(select(KnowledgeItem).where(KnowledgeItem.base_id.in_(bases),KnowledgeItem.deprecated.is_(False),active_filter('knowledge_item',KnowledgeItem.id))).all():
            revision=db.get(KnowledgeRevision,item.current_revision_id) if item.current_revision_id else None
            source=db.get(DocumentVersion,revision.source_version_id) if revision and revision.confirmed else None
            doc=db.get(Document,source.document_id) if source else None
            if not doc or is_deleted(db,'document',doc.id) or source.status!='published' or doc.current_version_id!=source.id: continue
            rows.append({'citation_id':revision.id,'document_id':doc.id,'document_version_id':source.id,'title':item.name,'filename':source.filename,
                         'version':source.label,'locator':revision.locator,'excerpt':revision.content,'scope':'formal','status':source.status,'formal':True,'current':True})
    rows=number_candidates(rows,numbers(query))
    ranked=rank(rows,query,60)
    if not numbers(query) and re.search(r'总结|概述|大致|解释|介绍|梳理|全文|附件|文件',data.content):
        selected_rows=[r for r in rows if r['scope']=='selected']
        if selected_rows:
            existing={r['citation_id'] for r in ranked}
            ranked.extend({**r,'score':.1} for r in selected_rows if r['citation_id'] not in existing)
            meta['warnings'].append('文件概述使用本次展示的章节片段，不代表已完整审阅全文。')
    config=db.scalar(select(ModelConfig).where(ModelConfig.kind=='embedding',ModelConfig.enabled.is_(True)).order_by(ModelConfig.created_at.desc()))
    if config and any(model_id==config.id for model_id,_ in vectors.values()):
        try:
            q=embeddings(config,[query])[0]
            scores={r['citation_id']:r for r in ranked}
            for row in rows:
                model_id,vector=vectors.get(row['citation_id'],(None,None))
                if model_id!=config.id or vector is None or len(q)!=len(vector): continue
                if numbers(query) and not numbers(query)<=numbers(row['title']+' '+row.get('filename','')+' '+row['excerpt']): continue
                cosine=sum(a*b for a,b in zip(q,vector))/(math.sqrt(sum(a*a for a in q))*math.sqrt(sum(b*b for b in vector)) or 1)
                if cosine<settings.qa_semantic_threshold: continue
                prior=scores.get(row['citation_id'],{**row,'score':0})
                scores[row['citation_id']]={**prior,'score':prior['score']+cosine*3}
            ranked=sorted(scores.values(),key=lambda r:-r['score'])
            meta['retrieval']='关键词检索＋可用的正式语义索引'
            if any(scope!='formal' for _,_,scope in versions.values()): meta['warnings'].append('个人资料与所选文件使用章节关键词检索；尚未建立这些资料的向量索引。')
        except Exception:
            meta['retrieval']='关键词检索';meta['warnings'].append('语义检索暂不可用，已降级为关键词检索。')
    else:
        meta['retrieval']='关键词检索';meta['warnings'].append('未配置可用的向量模型或缺少兼容的正式索引，当前使用关键词与章节匹配。')
    evidence=[];seen=set();counts=Counter();budget=0
    # Explicit files come first, while still requiring question relevance.
    ranked=sorted(ranked,key=lambda r:(r['scope']!='selected',-r['score']))
    for row in ranked:
        key=(row['document_version_id'],row['locator'],row['excerpt'])
        if key in seen or counts[row['document_version_id']]>=5: continue
        if budget+len(row['excerpt'])>settings.qa_context_char_limit: break
        seen.add(key);counts[row['document_version_id']]+=1;budget+=len(row['excerpt']);evidence.append(row)
        if len(evidence)>=14: break
    if can_search and 'mine' in scopes and (data.qa_mode=='analysis' or numbers(query)):
        evidence.extend(records(db,user,query,include_runs=include_task_records))
        if any(c.get('scope')=='public_ledger' for c in evidence): meta['warnings'].append('公共澄清计划为登记记录，公开可见不代表已经审核发布为正式规则。')
    meta['candidate_count']=len(rows);meta['evidence_count']=len(evidence)
    meta['document_count']=len({r.get('document_version_id') for r in evidence if r.get('document_version_id')})
    meta['unreviewed_count']=len({r.get('document_version_id') or r.get('record_id') for r in evidence if not r.get('formal')})
    meta['selected_versions']=list(data.version_ids) if 'selected' in scopes else []
    if numbers(query) and not evidence: meta['notice']='在当前范围中未找到该编号的可靠依据，未使用其他需求编号替代。'
    return evidence,meta


def instructions(mode,meta):
    return ('\n必须输出JSON对象，格式为 {"claims":[{"kind":"fact|inference|verify","text":"结论", "evidence_ids":["本次citation_id"], "evidence_quotes":[{"citation_id":"本次citation_id","quote":"逐字摘录支持此结论的原文，不少于4字"}]}]}。'
            '第一条结论直接回答用户的问题，随后补充必要细节和适用限制。合并重复内容；结论正文不写通用标题、检索过程、来源编号或原文摘录。'
            '每条先输出kind和text，随后输出evidence_ids与evidence_quotes，便于边生成边展示正文。'
            '每个已记载事实必须为每个引用提供可逐字匹配excerpt的原文，不能仅凭关联词认定。推导用inference，缺少依据或冲突用verify。'
            '未审核资料仅能描述为该资料记载，不得声称正式生效。资料相互冲突时分别说明。禁止输出citation_id以外的伪造来源。'
            '现行规则以current为true的正式版本为准；只有未审核资料时明确尚未找到正式依据。历史版本只用于明确的历史比较，不冒充现行规则。'
            '比较模式按新增、删除、修改分别逐项说明左右版本、规则、业务影响，引用左右原文，不能把文字变化直接认定为已生效业务规则。'
            '分析模式区分已证实规则、潜在影响、建议核实。不得把任务登记或候选关联当成正式规则。'
            '\n本次模式：'+MODE_NAMES[mode]+'；检索说明：'+json.dumps(meta,ensure_ascii=False))


def validate_answer(raw,evidence,mode):
    """Render only structured claims with valid supplied source IDs.

    This validates citation membership and status, not semantic entailment; users
    must still verify the source excerpts, especially inferred impacts.
    """
    try:
        value=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip()))
        claims=value.get('claims',[])
        if not isinstance(claims,list): raise ValueError()
    except (ValueError,AttributeError,TypeError):
        return '本次回答未通过来源格式校验，请重试；文档和业务数据未改变。',[],['模型返回的结论格式无效，未展示未校验正文。']
    by_id={r['citation_id']:r for r in evidence};used=[];groups={'fact':[],'inference':[],'verify':[]};warnings=[]
    quotes_by_id={}
    answer_parts=[]
    for claim in claims[:80]:
        if not isinstance(claim,dict) or not isinstance(claim.get('text'),str) or not claim['text'].strip(): continue
        kind=claim.get('kind','verify');kind=kind if kind in groups else 'verify'
        ids=claim.get('evidence_ids',[])
        ids=list(dict.fromkeys(x for x in ids if isinstance(x,str))) if isinstance(ids,list) else []
        valid=bool(ids) and all(i in by_id for i in ids)
        quotes=claim.get('evidence_quotes',[])
        quotes=quotes if isinstance(quotes,list) else []
        matched_quotes={}
        for quote in quotes:
            if not isinstance(quote,dict): continue
            cid=quote.get('citation_id');snippet=quote.get('quote')
            if isinstance(cid,str) and cid in ids and cid in by_id and isinstance(snippet,str) and len(snippet.strip())>=4 and snippet.strip() in by_id[cid].get('excerpt',''):
                matched_quotes[cid]=snippet.strip()
        text=claim['text'].strip()
        # Raw internal IDs never become document prose or fabricated inline links.
        text=re.sub(r'\[citation_id\s*:[^\]]*\]','',text)
        text=re.sub(r'!?\[([^\]]*)\]\([^)]*\)',r'\1',text)
        if kind!='verify' and not valid:
            warnings.append('部分结论缺少有效来源，已移除。');continue
        if kind=='fact' and any(cid not in matched_quotes for cid in ids):
            warnings.append('部分事实未提供可匹配的原文依据，已移除。');continue
        if kind=='fact' and any(not by_id[i].get('formal') for i in ids):
            text='【未审核资料／登记记录】'+text
        if kind=='inference': text='【推导，待人工确认】'+text
        refs=[]
        for cid in ids:
            if cid not in by_id: continue
            if cid not in used: used.append(cid)
            refs.append(str(used.index(cid)+1))
            if cid in matched_quotes:
                quotes_by_id.setdefault(cid,{}).setdefault(matched_quotes[cid],None)
        line=text+('〔来源'+ '、'.join(refs)+'〕' if refs else '')
        if mode=='knowledge': answer_parts.append(line)
        else: groups[kind].append(line)
    if mode!='knowledge':
        labels={'fact':'资料记载','inference':'潜在影响与推导','verify':'建议核实'}
        answer_parts=['### '+labels[k]+'\n\n'+'\n'.join('- '+t for t in lines) for k,lines in groups.items() if lines]
    result='\n\n'.join(answer_parts)
    citations=[{**by_id[c],'quotes':list(quotes_by_id[c])} if c in quotes_by_id else by_id[c] for c in used]
    return result or '未形成有可靠来源支持的结论，请补充资料或缩小问题范围。',citations,list(dict.fromkeys(warnings))
