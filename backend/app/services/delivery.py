"""Versioned delivery contract shared by generation, checks and export."""
import re
from fastapi import HTTPException

SRS_TEMPLATE={'id':'srs','version':'2.0','name':'软件需求说明书标准模板',
 'outline':['文档基本信息','1 需求背景与目标','1.1 需求背景','1.2 需求目标','2 整体业务方案概述','3 核心功能需求','4 接口与数据要求','5 非功能要求','6 验收与待确认事项'],
 'function_fields':['改造位置','适用角色','触发条件','输入字段','处理规则','异常处理','系统边界','验收点'],
 'page':{'size':'A4','margin_cm':2.54,'font':'等线','size_pt':11}}

def contract(config):
    value=config.get('delivery_template') or SRS_TEMPLATE
    return {**SRS_TEMPLATE,**value,'page':{**SRS_TEMPLATE['page'],**value.get('page',{})}}

def validate_contract(value):
    if not value:return
    from .outlines import normalize_outline
    try:
        if not isinstance(value,dict) or not isinstance(value.get('version'),str) or not 1<=len(value['version'])<=80:raise ValueError()
        normalize_outline(value.get('outline',[]))
        if not isinstance(value.get('function_fields',[]),list) or any(not isinstance(x,str) or len(x)>100 for x in value.get('function_fields',[])):raise ValueError()
        if len(str(value))>24000:raise ValueError()
        page=value.get('page',{})
        if not isinstance(page,dict) or page.get('size','A4') not in ('A4','Letter') or not .5<=float(page.get('margin_cm',2.54))<=5 or not 6<=float(page.get('size_pt',11))<=32 or not isinstance(page.get('font','等线'),str):raise ValueError()
    except (ValueError,TypeError):raise HTTPException(422,'交付模板需要版本、有效章节目录和功能字段列表')

def quality(content,template=None):
    template=template or SRS_TEMPLATE
    issues=[];headings=re.findall(r'^#{1,6}\s+(.+)$',content,re.M)
    seen=set()
    for h in headings:
        key=re.sub(r'\s+','',h)
        if key in seen:issues.append({'kind':'duplicate','message':'重复标题：'+h})
        seen.add(key)
    for title in template['outline']:
        name=re.sub(r'^\d+(?:\.\d+)*\s*','',title)
        if name not in content:issues.append({'kind':'missing_section','message':'缺少章节：'+title})
    if re.search(r'\[citation_id\s*:',content,re.I):issues.append({'kind':'citation','message':'正文仍有内部引用标记'})
    unresolved=len(re.findall(r'待确认|待核实|待补充',content))
    return {'template_id':template['id'],'template_version':template['version'],'issues':issues,'unresolved_count':unresolved,'notice':'结构检查与 AI 核查均不能替代人工会签。'}
