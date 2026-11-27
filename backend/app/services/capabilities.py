"""Bundled capabilities; existing skill versions and custom instructions stay intact."""
from sqlalchemy import select
from ..models import Skill,SkillVersion
from ..schemas import SkillConfig

CAPABILITIES=[
 ('analysis','业务需求解析与归一','/需求解析','提取需求编号、系统、项目、角色、当前行为、目标行为、来源及系统边界，输出候选供人工确认，禁止自动合并台账行。'),
 ('clarification','需求缺口识别','/澄清计划','识别需求缺失、冲突、歧义和阻塞事项；逐项给出问题、证据、原因、建议确认对象及是否阻塞生成。'),
 ('impact','变更影响分析','/关联分析','逐项分析受影响的功能、流程、字段、接口、系统；区分有直接依据的事实与建议核实的推断。'),
 ('ledger_fill','澄清台账自动填报','/澄清台账填报','依据业务资料填写对应需求的澄清台账，遵循原表列顺序，未知值留空，保留已登记内容并等待人工确认。'),
 ('quality','软需质量核查','/软需质检','依据业务原文核对软需完整性、重复与冲突、功能到验收覆盖、异常规则、系统边界及未决事项。输出缺陷与修复建议，不能替代人工审核，也不直接改正文。')]

def install(db,actor_id=None):
    changed=[]
    for workflow,name,command,prompt in CAPABILITIES:
        skill=db.scalar(select(Skill).where(Skill.command==command,Skill.public.is_(True)))
        if skill:
            if workflow=='ledger_fill':continue
            old=db.get(SkillVersion,skill.current_version_id)
            if old.config.get('package_metadata',{}).get('capability_revision')=='2':continue
            if workflow in ('impact','clarification') and old.config.get('system_prompt')!='依据提供的业务证据执行任务，缺少证据时说明无法确认。':continue
            cfg={**old.config,'system_prompt':prompt}
        else:
            skill=Skill(owner_id=actor_id,name=name,command=command,description=prompt,public=True)
            db.add(skill);db.flush();cfg=SkillConfig(workflow=workflow,system_prompt=prompt).model_dump()
        cfg['package_metadata']={**cfg.get('package_metadata',{}),'capability_revision':'2'}
        version=SkillVersion(skill_id=skill.id,creator_id=actor_id,config=cfg)
        db.add(version);db.flush();skill.current_version_id=version.id;skill.name=name;skill.description=prompt;changed.append(skill.id)
    return changed
