"""Resolve business identities without merging ledger rows or crossing ownership."""
import re
from fastapi import HTTPException
from sqlalchemy import select
from ..models import Requirement,User,RequirementContext
from .deletion import requirement_filter

def normalized(value):return re.sub(r'[\s_\-]+','',str(value)).casefold()

def number_key(number):
    text=str(number).strip()
    m=re.fullmatch(r'(?i)(?:RM[\s_-]*)?(\d{5,})(?:\.0)?',text)
    return str(int(m[1])) if m else normalized(text)

def business_rows(db,user):
    return db.scalars(select(Requirement).where(Requirement.owner_id==user.id,requirement_filter(),~Requirement.id.in_(select(RequirementContext.requirement_id).where(RequirementContext.kind!='business')))).all()

def business_requirements_by_number(db,user,number):
    target=number_key(number) if number is not None else ''
    return [row for row in business_rows(db,user) if number_key(row.number)==target] if target else []

def key(number,tags):
    return (number_key(number),tuple(sorted(normalized(x) for x in tags.get('系统',[]))),tuple(sorted(normalized(x) for x in tags.get('项目',[]))))

def check_identity(db,user,number,tags,exclude=None):
    target=key(number,tags)
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    for row in business_rows(db,user):
        if row.id!=exclude and key(row.number,row.tags)==target:
            raise HTTPException(409,{'message':'同一系统、项目下已有该编号需求，请关联已有需求；不同业务请补充系统或项目。','requirement_id':row.id,'title':row.title})

def ledger_matches(db,user,fields):
    candidates=[]
    values=' '.join(str(v) for k,v in fields.items() if any(t in k for t in ('编号','需求号','系统','项目')))
    ids={str(int(n)) for n in re.findall(r'\d{5,}',values)}
    for r in business_rows(db,user):
        digits=re.findall(r'\d{5,}',r.number)
        if (digits and any(str(int(d)) in ids for d in digits)) or normalized(r.number) in normalized(values) and len(normalized(r.number))>=5:
            candidates.append({'id':r.id,'number':r.number,'title':r.title})
    return candidates

def ledger_requirement_tags(fields):
    tags={}
    for category,columns in [('系统',('系统','所属系统','应用系统','涉及系统')),('项目',('项目','项目名称'))]:
        value=next((str(fields[c]).strip() for c in columns if fields.get(c)),None)
        if value:tags[category]=[value]
    return tags


def ledger_requirement(db,user,fields):
    tags=ledger_requirement_tags(fields)
    matches=[r for r in business_rows(db,user) if key(r.number,r.tags)==key(fields['需求编号'],tags)]
    if len(matches)>1:return None  # Historic ambiguity requires explicit user association.
    if matches:return matches[0]
    return create_ledger_requirement(db,user,fields,tags)


def create_ledger_requirement(db,user,fields,tags):
    r=Requirement(owner_id=user.id,number=str(fields['需求编号']),title=str(fields.get('需求名称') or fields['需求编号']),tags=tags)
    db.add(r);db.flush();return r
