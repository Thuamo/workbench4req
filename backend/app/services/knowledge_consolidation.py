import io
import json
from dataclasses import dataclass
from pathlib import Path

from docx import Document as WordDocument
from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated, Literal

from ..models import Document, DocumentVersion, KnowledgeBase, User
from ..security import audit, digest, require_base, write_lock
from .ai import SYSTEM_POLICY, complete
from .deletion import active_filter
from .files import blob, isolated_parse, store, validate

TARGET_BASE = '业务领域知识库'
SOURCE_GROUPS = (
    ('需求澄清知识库', '软件需求澄清库', '软件需求澄清知识库'),
    ('平台基础资料库',),
)
TARGET_FORMATS = (('执行能力地图', '.xlsx'), ('白皮书', '.docx'))
MAX_SOURCE_FILES = 40

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Detail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


class Finding(BaseModel):
    capability: ShortText
    map_update: Detail
    whitepaper_update: Detail
    assessment: Literal['资料已说明', '推断待核实', '冲突待澄清']
    evidence: list[str] = Field(min_length=1, max_length=5)


class Analysis(BaseModel):
    changes: list[Finding] = Field(max_length=15)


@dataclass
class Input:
    document: Document
    version: DocumentVersion
    base_name: str

    def describe(self):
        return {'document_id': self.document.id, 'version_id': self.version.id,
                'title': self.document.title, 'label': self.version.label}


@dataclass
class Consolidation:
    groups: list[dict]
    sources: list[Input]
    targets: list[Input]
    issues: list[str]

    def describe(self):
        return {'sources': self.groups, 'targets': [item.describe() for item in self.targets],
                'issues': self.issues, 'max_source_files': MAX_SOURCE_FILES}

    def signature(self):
        state = [[item.base_name, item.document.id, item.document.title, item.version.id,
                  item.version.file_hash, item.version.content_hash] for item in self.sources + self.targets]
        return digest(json.dumps(state, ensure_ascii=False))


def inspect(db: Session, base_id: str, user: User) -> Consolidation:
    base = require_base(db, base_id, user)
    if base.name != TARGET_BASE:
        raise HTTPException(404, '知识沉淀入口仅在业务领域知识库开放')
    groups, sources, targets, issues = [], [], [], []
    for names in SOURCE_GROUPS:
        grouped = db.scalars(select(KnowledgeBase).where(KnowledgeBase.name.in_(names)).order_by(KnowledgeBase.name)).all()
        count = 0
        restricted = False
        for source in grouped:
            if not source.enabled:
                continue
            # Any reader of the target must be allowed to read the source.
            if not source.public and (base.public or not set(base.member_ids).issubset(source.member_ids)):
                restricted = True
                continue
            versions = db.execute(select(Document, DocumentVersion).join(
                DocumentVersion, Document.current_version_id==DocumentVersion.id).where(
                Document.base_id==source.id, active_filter('document', Document.id),
                DocumentVersion.status=='published', DocumentVersion.publish_status=='published',
                DocumentVersion.parse_status=='ready', DocumentVersion.content!=''
            ).order_by(Document.title, Document.id)).all()
            count += len(versions)
            sources.extend(Input(doc, version, source.name) for doc, version in versions)
        groups.append({'name': ' / '.join(source.name for source in grouped) or names[0],
                       'ready_count': count, 'restricted': restricted})
    if not sources:
        issues.append('两个来源库均无可用的正式文件')
    if len(sources) > MAX_SOURCE_FILES:
        issues.append(f'当前有 {len(sources)} 份正式资料，超过单次沉淀上限 {MAX_SOURCE_FILES} 份')

    documents = db.scalars(select(Document).where(Document.base_id==base.id,
                         active_filter('document', Document.id))).all()
    for keyword, suffix in TARGET_FORMATS:
        matching = [doc for doc in documents if keyword in doc.title]
        if len(matching) != 1:
            issues.append(f'请在业务领域知识库中保留一份可唯一识别的{keyword}资产')
            continue
        doc = matching[0]
        version = db.get(DocumentVersion, doc.current_version_id) if doc.current_version_id else None
        if not version and not doc.current_version_id:
            drafts = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id,
                                DocumentVersion.status=='draft').order_by(DocumentVersion.created_at.desc())).all()
            version = next((item for item in drafts if not item.provenance.get('knowledge_consolidation')
                            and Path(item.filename).suffix.lower()==suffix), None)
        if not version or version.parse_status != 'ready' or Path(version.filename).suffix.lower()!=suffix:
            issues.append(f'请为「{doc.title}」提供已解析的 {suffix} 原文件')
            continue
        targets.append(Input(doc, version, base.name))
    return Consolidation(groups, sources, targets, issues)


def excerpts(item: Input, budget: int) -> list[dict]:
    blocks = [block for block in item.version.blocks if block.get('text', '').strip()]
    if not blocks:
        blocks = [{'locator': '正文', 'text': item.version.content}]
    total = sum(len(block['text']) for block in blocks)
    if total <= budget and len(blocks) <= 100:
        selected = blocks
        per_block = budget
    else:
        # Sample across the document, including the beginning and end, within the model budget.
        count = min(len(blocks), max(2, budget//220), 100)
        positions = [i*(len(blocks)-1)//max(1, count-1) for i in range(count)]
        selected = [blocks[index] for index in positions]
        per_block = budget//count
    return [{'locator': block['locator'], 'text': block['text'][:per_block]} for block in selected]


def analyze(db: Session, user: User, inputs: Consolidation):
    references, files = {}, []
    for item in inputs.sources:
        evidence = excerpts(item, min(12_000, 48_000//len(inputs.sources)))
        for excerpt in evidence:
            key = f'S{len(references)+1}'
            excerpt['id'] = key
            references[key] = {'base_name': item.base_name, 'title': item.document.title, 'label': item.version.label,
                               'document_id': item.document.id, 'document_version_id': item.version.id,
                               'locator': excerpt['locator'], 'citation_id': key}
        files.append({'library': item.base_name, 'title': item.document.title, 'evidence': evidence})
    baselines = [{'title': item.document.title, 'excerpts': excerpts(item, 8500)} for item in inputs.targets]
    raw, trace = complete(db, user.id, [
        {'role': 'system', 'content': SYSTEM_POLICY + '\n比较来源资料与现有授信执行能力地图和白皮书。只提交对执行能力、业务流程、边界或依赖规则有实质影响的新知识或矛盾。'
         '同一变化只列一次；每条分别给出能力地图条目和白皮书可直接采用的业务说明。'
         '来源库为片段，无法判断是否已有记载时标为待核实。对推断和冲突说明待验证内容，不得编造规则。'
         '输出 JSON {"changes":[{"capability":"能力名称","map_update":"能力地图建议","whitepaper_update":"白皮书说明",'
         '"assessment":"资料已说明|推断待核实|冲突待澄清","evidence":["S1"]}]}。'
         '每条引用 1 至 5 个实际支持它的来源片段，最多 15 条，无依据时返回空数组。'},
        {'role': 'user', 'content': json.dumps({'来源资料': files, '现有文件': baselines}, ensure_ascii=False)},
    ], json_output=True)
    db.commit()
    try:
        findings = Analysis.model_validate_json(raw).changes
    except ValidationError as error:
        raise HTTPException(502, '模型生成结果格式不完整，请重试') from error
    if any(set(finding.evidence)-references.keys() for finding in findings):
        raise HTTPException(502, '模型生成结果引用了无效的资料片段，请重试')
    return findings, references, trace


def finding_sources(finding, references):
    return [references[key] for key in dict.fromkeys(finding.evidence)]


def display_source(source):
    return f'{source["base_name"]} / {source["title"]} · {source["label"]} / {source["locator"]}'


def update_workbook(original, findings, references):
    workbook = load_workbook(original, keep_links=True)
    try:
        sheet = workbook.create_sheet('知识沉淀')
        sheet.append(['执行能力', '能力地图更新建议', '判断', '来源资料与定位'])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for finding in findings:
            evidence = '\n'.join(map(display_source, finding_sources(finding, references)))
            sheet.append([finding.capability, finding.map_update, finding.assessment, evidence])
            for cell in sheet[sheet.max_row]:
                cell.data_type = 's'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for col, width in zip('ABCD', (24, 68, 18, 54)):
            sheet.column_dimensions[col].width = width
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        workbook.active = sheet
        result = io.BytesIO()
        workbook.save(result)
        return result.getvalue()
    finally:
        workbook.close()


def update_whitepaper(original, findings, references):
    document = WordDocument(original)
    document.add_heading('知识沉淀更新建议', level=1)
    for finding in findings:
        document.add_heading(finding.capability, level=2)
        document.add_paragraph(finding.whitepaper_update)
        document.add_paragraph('判断 · '+finding.assessment)
        for source in finding_sources(finding, references):
            document.add_paragraph('依据 · '+display_source(source))
    result = io.BytesIO()
    document.save(result)
    return result.getvalue()


def previous_drafts(db: Session, inputs: Consolidation, signature: str):
    saved = []
    for target in inputs.targets:
        versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==target.document.id,
                  DocumentVersion.status.in_(('draft', 'pending_review', 'in_review', 'approved')))).all()
        saved.extend(Input(target.document, version, target.base_name) for version in versions
                     if version.provenance.get('knowledge_consolidation', {}).get('signature')==signature
                     and version.review_status!='returned')
    if len(saved)==len(inputs.targets) and len({item.document.id for item in saved})==len(inputs.targets):
        return [item.describe() for item in saved]
    return []


def consolidate(db: Session, base_id: str, user: User):
    inputs = inspect(db, base_id, user)
    if inputs.issues:
        raise HTTPException(422, '；'.join(inputs.issues))
    signature = inputs.signature()
    existing = previous_drafts(db, inputs, signature)
    if existing:
        return {'drafts': existing, 'reused': True}
    findings, references, trace = analyze(db, user, inputs)
    if not findings:
        return {'drafts': [], 'reused': False}

    artifacts = []
    for target, render in zip(inputs.targets, (update_workbook, update_whitepaper)):
        with blob(target.version.file_hash).open('rb') as baseline:
            data = render(baseline, findings, references)
        filename = validate(data, target.version.filename)
        file_hash = store(data)
        artifacts.append((filename, file_hash, isolated_parse(file_hash, filename)))

    write_lock(db)
    db.scalar(select(KnowledgeBase).where(KnowledgeBase.id==base_id).with_for_update())
    verified = inspect(db, base_id, user)
    if verified.issues or verified.signature()!=signature:
        raise HTTPException(409, '来源资料或目标版本已变化，请重新分析')
    existing = previous_drafts(db, verified, signature)
    if existing:
        return {'drafts': existing, 'reused': True}
    used = list(dict.fromkeys(key for finding in findings for key in finding.evidence))
    created = []
    for target, (filename, file_hash, parsed) in zip(verified.targets, artifacts):
        label = f'知识沉淀-{signature[:8]}'
        assigned = set(db.scalars(select(DocumentVersion.label).where(DocumentVersion.document_id==target.document.id)).all())
        candidate = label
        sequence = 2
        while candidate in assigned:
            candidate = f'{label}-{sequence}'
            sequence += 1
        version = DocumentVersion(document_id=target.document.id, creator_id=user.id, parent_id=target.version.id,
                   label=candidate, filename=filename, file_hash=file_hash, content_hash=digest(parsed['content']),
                   content=parsed['content'], blocks=parsed['blocks'], warnings=parsed['warnings'], parse_status='ready',
                   change_note=f'基于正式资料沉淀 {len(findings)} 项建议，待人工审核。',
                   provenance={'sources': [references[key] for key in used],
                               'knowledge_consolidation': {'signature': signature, 'model': trace.get('model'),
                                'inputs': [item.describe() for item in verified.sources]}})
        db.add(version)
        db.flush()
        created.append(Input(target.document, version, target.base_name).describe())
    audit(db, user, 'knowledge.consolidation', base_id, drafts=created, signature=signature, findings=len(findings))
    db.commit()
    return {'drafts': created, 'reused': False}
