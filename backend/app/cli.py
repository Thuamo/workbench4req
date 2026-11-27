import argparse, getpass, secrets
from sqlalchemy import select
from .db import SessionLocal
from .models import User, KnowledgeBase, Skill, SkillVersion, Setting
from .security import hasher
from .schemas import SkillConfig
from .password_policy import MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH


def seed(db):
    for name in ['业务领域知识库','平台基础资料库','历史业务需求库','软件需求说明书库','需求澄清知识库','需求模板库']:
        if not db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.name==name)):
            db.add(KnowledgeBase(name=name,description='所有正式文件须经多人审核与索引发布'))
    for name,command,workflow,description in [('澄清计划','/澄清计划','clarification','识别业务需求缺口，生成待人工确认的问题清单'),('软需生成','/软需生成','specification','检索证据、确认提纲、分章节生成与质量校验'),('关联分析','/关联分析','impact','按系统、模块、接口和规则分析潜在影响'),('知识库问答','/知识库问答','qa','基于正式有效知识给出带版本来源的回答')]:
        if not db.scalar(select(Skill.id).where(Skill.command==command,Skill.public.is_(True))):
            skill=Skill(name=name,command=command,description=description,public=True)
            db.add(skill)
            db.flush()
            version=SkillVersion(skill_id=skill.id,config=SkillConfig(workflow=workflow).model_dump())
            db.add(version)
            db.flush()
            skill.current_version_id=version.id
    if not db.scalar(select(Setting.id).where(Setting.key=='scoring')):
        db.add(Setting(key='scoring',value={'version':'1','interface_weight':2,'rule_weight':2,'module_weight':1}))
        db.add(Setting(key='tags',value={k:[] for k in ['业务领域','系统','模块','需求类型','变更类型','数据接口','业务规则','需求状态','复杂度','影响范围']}))
    from .services.capabilities import install
    install(db)
    from .services.uml import install as install_uml
    install_uml(db)
    from .services.ppt_report import install as install_ppt_report
    install_ppt_report(db)
    from .services.mind_map import install as install_mind_map
    install_mind_map(db)
    from .services.requirement_initialization import CHANGE_COMMAND
    if not db.scalar(select(Skill.id).where(Skill.command==CHANGE_COMMAND,Skill.public.is_(True))):
        skill=Skill(name='软需变更',command=CHANGE_COMMAND,public=True,
                    description='以当前需求包的软需版本为基线，按新增资料或变更说明生成新版草稿')
        db.add(skill)
        db.flush()
        config=SkillConfig(workflow='specification',human_confirmation=False,
            system_prompt='根据基线软需与本次变更依据生成完整新版。保留未受影响的内容，只按证据调整受影响章节和验收标准。不要把旧基线中的已修改规则作为新版规则。')
        version=SkillVersion(skill_id=skill.id,config=config.model_dump())
        db.add(version)
        db.flush()
        skill.current_version_id=version.id
    db.commit()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['seed','init-admin'])
    parser.add_argument('--username')
    parser.add_argument('--display-name',default='系统管理员')
    args=parser.parse_args()
    with SessionLocal() as db:
        seed(db)
        if args.command=='init-admin':
            if db.scalar(select(User.id).where(User.role=='super_admin')):
                raise SystemExit('管理员已经初始化；请在系统管理中配置其他用户')
            username=args.username or input('管理员用户名：').strip()
            password=getpass.getpass(f'密码（至少{MIN_PASSWORD_LENGTH}位）：')
            confirm=getpass.getpass('确认密码：')
            if len(username)<3 or not MIN_PASSWORD_LENGTH<=len(password)<=MAX_PASSWORD_LENGTH or password!=confirm:
                raise SystemExit('用户名或密码不符合要求')
            db.add(User(username=username,display_name=args.display_name,password_hash=hasher.hash(password),role='super_admin'))
            db.commit()
            print('管理员已创建；密码未写入源码')


if __name__=='__main__':
    main()
