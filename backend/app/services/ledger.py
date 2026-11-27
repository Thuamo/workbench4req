import io, json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, time, timedelta
from openpyxl import load_workbook, Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import ClarificationTask, TaskHistory, User, Setting, Question, Audit, DeletedRecord, uid
from ..security import digest, audit, write_lock
from fastapi import HTTPException
from .deletion import active_filter
from .identity import business_rows, create_ledger_requirement, ledger_requirement_tags, number_key


FIELDS=['需求编号','需求名称','申请部门','业务对接人','澄清周','业务紧急程度','实施对接人','软需负责人','澄清时间','澄清结果','会议结论','备注','关注程度','软需进展','软需完成时间','业务对象','业务阶段','产品名称','需求价值目标','科技属性','改进方向','价值度量-客观价值','战略关联度-主观优先级','工作量']


def ledger_columns(db: Session,user: User) -> list[str]:
    saved=db.scalar(select(Setting).where(Setting.key=='ledger_columns:'+user.id))
    columns=list(saved.value.get('columns',[])) if saved else []
    tasks=db.scalars(select(ClarificationTask).where(ClarificationTask.owner_id==user.id,active_filter('clarification_task',ClarificationTask.id)).order_by(ClarificationTask.created_at)).all()
    for task in tasks:
        for key in task.fields:
            if key not in columns:
                columns.append(key)
    return FIELDS.copy() if not columns or (not saved and set(columns).issubset(FIELDS)) else columns


def public_ledger_columns(db: Session) -> list[str]:
    rows=db.scalars(select(ClarificationTask).where(active_filter('clarification_task',ClarificationTask.id)).order_by(ClarificationTask.created_at,ClarificationTask.id)).all()
    owners=list(dict.fromkeys(t.owner_id for t in rows))
    # The latest imported table defines the leading order for every viewer.
    undone=select(Audit.resource_id).where(Audit.action=='ledger.import_undo')
    latest=db.scalar(select(Audit).where(Audit.action=='ledger.import',Audit.actor_id.in_(owners),
                    Audit.resource_id.not_in(undone)).order_by(Audit.created_at.desc(),Audit.id.desc())) if owners else None
    if latest: owners=[latest.actor_id,*[owner for owner in owners if owner!=latest.actor_id]]
    columns=[]
    for owner in owners:
        saved=db.scalar(select(Setting).where(Setting.key=='ledger_columns:'+owner))
        for key in saved.value.get('columns',[]) if saved else []:
            if key not in columns: columns.append(key)
    for task in rows:
        for key in task.fields:
            if key not in columns: columns.append(key)
    return FIELDS.copy() if not columns or (not latest and set(columns).issubset(FIELDS)) else columns


def lock_ledger(db: Session,user: User):
    write_lock(db)
    db.scalar(select(User).where(User.id==user.id).with_for_update())


def has_value(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def excel_value(value):
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value) if isinstance(value, timedelta) else value


def parse_ledger(data: bytes):
    workbook=None
    try:
        workbook=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
        file_hash=digest(data)
        columns=[]
        entries=[]
        for sheet in workbook:
            rows=sheet.iter_rows(values_only=True)
            header=[str(x).strip() if x is not None else '' for x in next(rows,[])]
            if '需求编号' not in header or '需求名称' not in header:
                continue
            if len([name for name in header if name])!=len(set(name for name in header if name)):
                raise HTTPException(422,f'工作表“{sheet.title}”存在重复列名，请先为每列设置不同名称')
            for name in header:
                if name and name not in columns: columns.append(name)
            for row_number,row in enumerate(rows,2):
                fields={header[i]:excel_value(v) for i,v in enumerate(row) if i<len(header) and header[i]}
                if any(has_value(value) for value in fields.values()):
                    entries.append({'sheet':sheet.title,'row':row_number,'fields':fields})
        if not columns:
            raise HTTPException(422,'未找到包含“需求编号”和“需求名称”的表头，请检查上传工作表')
        if not any(has_value(entry['fields'].get('需求编号')) for entry in entries):
            raise HTTPException(422,'表格没有有效任务行，请至少填写一行需求编号')
        return {'columns':columns,'entries':entries,'file_hash':file_hash}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(422,'Excel 文件无法读取，请检查文件格式和内容后重新上传') from error
    finally:
        if workbook is not None: workbook.close()


@dataclass
class ImportRow:
    source: dict
    action: str
    task: ClarificationTask | None = None
    changes: dict | None = None
    requirement_id: str | None = None
    reason: str = ''

    def summary(self):
        fields = self.source['fields']
        return {'sheet': self.source['sheet'], 'row': self.source['row'],
                'number': str(fields['需求编号']) if has_value(fields.get('需求编号')) else '',
                'name': str(fields.get('需求名称') or ''),
                'action': self.action, 'reason': self.reason, 'changed_fields': list(self.changes or {}),
                'associate_requirement': bool(self.requirement_id and self.task and not self.task.requirement_id)}


def ledger_number(fields):
    number = fields.get('需求编号')
    return number_key(number) if has_value(number) else ''


def plan_ledger(db: Session, user: User, parsed: dict):
    tasks = db.scalars(select(ClarificationTask).where(
        ClarificationTask.owner_id == user.id, active_filter('clarification_task', ClarificationTask.id),
    ).order_by(ClarificationTask.created_at, ClarificationTask.id)).all()
    existing, requirements = defaultdict(list), defaultdict(list)
    for task in tasks:
        existing[ledger_number(task.fields)].append(task)
    for requirement in business_rows(db, user):
        requirements[number_key(requirement.number)].append(requirement.id)
    incoming = Counter(ledger_number(entry['fields']) for entry in parsed['entries'])
    rows = []
    for entry in parsed['entries']:
        fields = entry['fields']
        number = ledger_number(fields)
        matches = existing[number]
        if not number or incoming[number] > 1 or len(matches) > 1:
            reason = '缺少有效需求编号' if not number else 'Excel 中的需求编号重复' if incoming[number] > 1 else '本人台账已有多条同编号计划'
            rows.append(ImportRow(entry, 'conflict', reason=reason))
            continue
        task = matches[0] if matches else None
        requirement_id = task.requirement_id if task else None
        candidates = requirements[number]
        if not requirement_id and len(candidates) > 1:
            rows.append(ImportRow(entry, 'conflict', reason='编号匹配多个业务需求，请人工核对'))
            continue
        if not requirement_id and candidates:
            requirement_id = candidates[0]
        if task is None:
            rows.append(ImportRow(entry, 'add', requirement_id=requirement_id))
            continue
        changes = {key: value for key, value in fields.items()
                   if key != '需求编号' and has_value(value) and task.fields.get(key) != value}
        action = 'update' if changes or requirement_id != task.requirement_id else 'unchanged'
        rows.append(ImportRow(entry, action, task, changes, requirement_id))

    saved = db.scalar(select(Setting).where(Setting.key == 'ledger_columns:' + user.id))
    previous_columns = saved.value.get('columns', []) if saved else None
    active_columns = (key for task in tasks for key in task.fields)
    columns = list(dict.fromkeys([*(previous_columns or []), *active_columns, *parsed['columns']]))
    # Confirm the same file against the same ledger revisions and requirement matches.
    snapshot = digest(json.dumps([
        user.id, parsed['file_hash'], previous_columns,
        sorted((task.id, task.revision, task.requirement_id) for task in tasks),
        [(row.action, row.requirement_id, row.reason) for row in rows],
    ], ensure_ascii=False, separators=(',', ':')))
    counts = Counter(row.action for row in rows)
    preview = {'existing_count': len(tasks), 'incoming_count': len(rows), 'columns': columns, 'snapshot': snapshot,
               'added': counts['add'], 'updated': counts['update'], 'unchanged': counts['unchanged'],
               'conflicts': counts['conflict']}
    return preview, rows, saved


def preview_ledger(db: Session, user: User, data: bytes):
    preview, rows, _ = plan_ledger(db, user, parse_ledger(data))
    return {**preview, 'rows': [row.summary() for row in rows]}


def clarification_status(value):
    value = str(value or '').strip()
    return {'澄清结束': 'completed', '已自行澄清': 'completed', '无需澄清': 'not_needed'}.get(
        value, 'in_progress' if value else 'pending',
    )


def import_ledger(db: Session, user: User, data: bytes, expected_snapshot: str | None = None, filename: str = '') -> dict:
    parsed = parse_ledger(data)
    lock_ledger(db, user)
    preview, rows, saved = plan_ledger(db, user, parsed)
    snapshot = preview.pop('snapshot')
    if expected_snapshot != snapshot:
        raise HTTPException(409, '文件或台账已变化，或缺少导入确认，请重新预览后导入')
    result = {**preview, 'batch_id': None}
    if not (preview['added'] or preview['updated']):
        return result

    entries = []
    for row in rows:
        if row.action == 'add':
            fields = row.source['fields']
            requirement_id = row.requirement_id
            if not requirement_id:
                requirement_id = create_ledger_requirement(db, user, fields, ledger_requirement_tags(fields)).id
            task = ClarificationTask(owner_id=user.id, requirement_id=requirement_id, fields=fields,
                                     status=clarification_status(fields.get('澄清结果')))
            db.add(task)
            db.flush()
            before = None
        elif row.action == 'update':
            task = row.task
            before = {'fields': task.fields, 'status': task.status, 'requirement_id': task.requirement_id}
            task.fields = {**task.fields, **row.changes}
            task.requirement_id = row.requirement_id
            if '澄清结果' in row.changes:
                task.status = clarification_status(row.changes['澄清结果'])
            task.revision += 1
        else:
            continue
        db.add(TaskHistory(task_id=task.id, actor_id=user.id, fields=task.fields, revision=task.revision))
        entries.append({'id': task.id, 'revision': task.revision, 'before': before})

    columns = preview['columns']
    columns_before = saved.value.get('columns', []) if saved else None
    if saved:
        saved.value = {'columns': columns}
    else:
        db.add(Setting(key='ledger_columns:' + user.id, value={'columns': columns}))
    batch_id = uid()
    audit(db, user, 'ledger.import', batch_id, mode='incremental', filename=filename, file_hash=parsed['file_hash'],
          added=preview['added'], updated=preview['updated'], conflicts=preview['conflicts'],
          columns_before=columns_before, columns_after=columns, entries=entries)
    db.commit()
    return {**result, 'batch_id': batch_id}


def ledger_import_batches(db: Session, user: User):
    logs = db.scalars(select(Audit).where(Audit.actor_id == user.id, Audit.action.in_(('ledger.import', 'ledger.import_undo')))
                      .order_by(Audit.created_at.desc(), Audit.id.desc())).all()
    undone = {log.resource_id for log in logs if log.action == 'ledger.import_undo'}
    return [{'id': log.resource_id, 'created_at': log.created_at, 'filename': log.detail['filename'],
             'added': log.detail['added'], 'updated': log.detail['updated'], 'undone': log.resource_id in undone}
            for log in logs if log.action == 'ledger.import' and log.detail.get('mode') == 'incremental']


def undo_ledger_import(db: Session, user: User, batch_id: str):
    lock_ledger(db, user)
    logs = db.scalars(select(Audit).where(Audit.actor_id == user.id, Audit.resource_id == batch_id,
                                           Audit.action.in_(('ledger.import', 'ledger.import_undo')))).all()
    batch = next((log for log in logs if log.action == 'ledger.import' and log.detail.get('mode') == 'incremental'), None)
    if batch is None:
        raise HTTPException(404, '导入批次不存在')
    if any(log.action == 'ledger.import_undo' for log in logs):
        return {'batch_id': batch_id, 'undone': True}

    entries = {entry['id']: entry for entry in batch.detail['entries']}
    tasks = db.scalars(select(ClarificationTask).where(ClarificationTask.id.in_(entries),
        ClarificationTask.owner_id == user.id, active_filter('clarification_task', ClarificationTask.id))).all()
    if len(tasks) != len(entries) or any(task.revision != entries[task.id]['revision'] for task in tasks):
        raise HTTPException(409, '本批次部分台账已修改或删除，无法整批撤销')
    added_ids = [task_id for task_id, entry in entries.items() if entry['before'] is None]
    if added_ids and db.scalar(select(Question.id).where(Question.task_id.in_(added_ids),
            active_filter('question', Question.id)).limit(1)):
        raise HTTPException(409, '本批次新增台账已有澄清问题关联，无法整批撤销')

    for task in tasks:
        before = entries[task.id]['before']
        if before is None:
            db.add(DeletedRecord(resource_type='clarification_task', resource_id=task.id, owner_id=user.id,
                                 deleted_by=user.id, reason='撤销增量导入批次'))
        else:
            task.fields = before['fields']
            task.status = before['status']
            task.requirement_id = before['requirement_id']
            task.revision += 1
            db.add(TaskHistory(task_id=task.id, actor_id=user.id, fields=task.fields, revision=task.revision))
    saved = db.scalar(select(Setting).where(Setting.key == 'ledger_columns:' + user.id))
    if saved and saved.value.get('columns', []) == batch.detail['columns_after']:
        if batch.detail['columns_before'] is None:
            db.delete(saved)
        else:
            saved.value = {'columns': batch.detail['columns_before']}
    audit(db, user, 'ledger.import_undo', batch_id, added=batch.detail['added'], updated=batch.detail['updated'])
    db.commit()
    return {'batch_id': batch_id, 'undone': True}


def export_ledger(tasks: list[ClarificationTask],columns: list[str] | None=None) -> bytes:
    wb=Workbook()
    sheet=wb.active
    sheet.title='信贷澄清及软需'
    fields=list(columns or [])
    for task in tasks:
        for key in task.fields:
            if key not in fields:
                fields.append(key)
    fields=fields or FIELDS.copy()
    sheet.append(fields)
    for task in tasks:
        values=[]
        for key in fields:
            value=task.fields.get(key)
            if isinstance(value,str) and value.startswith(('=','+','-','@')):
                value="'"+value
            values.append(value)
        sheet.append(values)
    sheet.freeze_panes='C2'
    sheet.auto_filter.ref=sheet.dimensions
    from openpyxl.styles import Font, PatternFill, Alignment
    for cell in sheet[1]:
        cell.font=Font(bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid',fgColor='254B7A')
    for row in sheet:
        for cell in row:
            cell.alignment=Alignment(vertical='top',wrap_text=True)
    for col in range(1,len(fields)+1):
        sheet.column_dimensions[__import__('openpyxl').utils.get_column_letter(col)].width=40 if col in (2,11,12) else 22
    output=io.BytesIO()
    wb.save(output)
    return output.getvalue()
