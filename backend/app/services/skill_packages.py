import io, json, re, stat, zipfile
from pathlib import PurePosixPath
import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from ..schemas import SkillInput


def package_files(data: bytes) -> dict[str,bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>256 or sum(item.file_size for item in entries)>32*1024*1024:
                raise HTTPException(422,'技能包展开体积或文件数量超出限制')
            result={}
            for item in entries:
                name=item.filename.replace('\\','/')
                path=PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or ':' in name or stat.S_ISLNK(item.external_attr>>16):
                    raise HTTPException(422,'技能包包含不安全的文件路径或符号链接')
                if not item.is_dir():
                    if name in result:
                        raise HTTPException(422,'技能包包含重复文件路径')
                    result[name]=archive.read(item)
            return result
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError):
        raise HTTPException(422,'技能包不是有效的未加密 ZIP 文件')


def read_skill_package(data: bytes,filename: str,workflow: str | None=None,preview: bool=False) -> tuple[SkillInput,list[str]]:
    if filename.lower().endswith(('.zip','.skill')):
        files=package_files(data)
    elif filename.lower().endswith(('.json','.md')):
        files={PurePosixPath(filename.replace('\\','/')).name:data}
    else:
        raise HTTPException(422,'请选择 ZIP、.skill、JSON 或 SKILL.md 文件')
    manifests=sorted([name for name in files if PurePosixPath(name).name.lower() in ('skill.json','manifest.json') or name.lower().endswith('.json') and len(files)==1],key=lambda name:(PurePosixPath(name).name.lower()!='skill.json',name.count('/')))
    markdowns=sorted([name for name in files if PurePosixPath(name).name.lower()=='skill.md' or name.lower().endswith('.md') and len(files)==1],key=lambda name:name.count('/'))
    try:
        if manifests:
            content=files[manifests[0]]
            if len(content)>1024*1024:
                raise ValueError('技能配置超过1MB')
            raw=json.loads(content.decode('utf-8-sig'))
            raw=raw.get('skill',raw)
            if not isinstance(raw,dict):
                raise ValueError('技能配置应为对象')
        elif markdowns:
            text=files[markdowns[0]].decode('utf-8-sig')
            if len(text)>1024*1024:
                raise ValueError('SKILL.md 超过1MB')
            metadata={}
            body=text
            match=re.match(r'^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)',text,re.S)
            if match:
                if len(match[1])>32768:
                    raise ValueError('技能元信息过长')
                metadata=yaml.safe_load(match[1]) or {}
                if not isinstance(metadata,dict):
                    raise ValueError('技能元信息应为对象')
                body=text[match.end():].strip()
            name=metadata.get('name') or PurePosixPath(markdowns[0]).parent.name or '导入技能'
            raw={'name':name,'description':metadata.get('description') or '从 SKILL.md 导入','command':metadata.get('command') or '/'+str(name),'config':{'system_prompt':body,'workflow':metadata.get('workflow')}}
        else:
            raise ValueError('包内需要 skill.json、manifest.json 或 SKILL.md')
        config=raw.get('config') or {'system_prompt':raw.get('system_prompt') or raw.get('prompt') or '依据实际来源执行任务','workflow':raw.get('workflow')}
        declared=config.get('workflow')
        if not declared and any(name.endswith('/scripts/clarification_row.py') for name in files):
            config={**config,'workflow':'ledger_fill'}
            declared='ledger_fill'
        if workflow: config={**config,'workflow':workflow}
        elif not declared:
            if not preview: raise HTTPException(422,'技能包未声明工作流，请在导入预览中明确选择工作流')
            config={**config,'workflow':'qa'}
        config['package_metadata']={'workflow_declared':bool(declared)}
        result=SkillInput.model_validate({'name':raw.get('name'),'command':raw.get('command') or '/'+str(raw.get('name','导入技能')),'description':raw.get('description','导入技能'),'public':False,'config':config})
        return result,list(files)
    except (ValueError,TypeError,AttributeError,UnicodeError,RecursionError,yaml.YAMLError,ValidationError):
        raise HTTPException(422,'技能包配置无效，请检查名称、描述、工作流、JSON 或 SKILL.md 元信息')


def export_skill_package(skill: dict,original: bytes | None=None) -> bytes:
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        config={**skill['config'],'package_metadata':{}}
        archive.writestr('skill.json',json.dumps({'format':'workbench-skill/v1','skill':{**skill,'public':False,'config':config}},ensure_ascii=False,indent=2))
        metadata=yaml.safe_dump({'name':skill['name'],'description':skill['description'],'command':skill['command'],'workflow':config['workflow']},allow_unicode=True,sort_keys=False)
        archive.writestr('SKILL.md','---\n'+metadata+'---\n\n'+config['system_prompt'])
        if original:
            archive.writestr('source/original-package.zip',original)
    return output.getvalue()
