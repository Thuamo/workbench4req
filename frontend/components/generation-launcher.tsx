'use client';
import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../lib/api';
import type {Skill,Requirement} from '../lib/types';
import type {PageKey} from './workbench';
import {Modal,SearchSelect,Loading} from './ui';
import {ExecuteModal} from './skill-execution';
export function GenerationLauncher({requirement,workflow='specification',close,navigate}:{requirement?:Requirement;workflow?:string;close:()=>void;navigate:(page:PageKey,id?:string)=>void}){
 const {data:skills,isLoading}=useQuery({queryKey:['skills'],queryFn:()=>api<Skill[]>('/skills')});const [id,setId]=useState('');const [start,setStart]=useState(false);
 const available=(skills||[]).filter(skill=>skill.enabled&&skill.config.workflow===workflow);const selected=available.find(skill=>skill.id===id)||available.find(skill=>skill.public)||available[0];
 if((start||available.length===1)&&selected)return <ExecuteModal skill={selected} defaultRequirement={requirement} close={close} complete={run=>{close();navigate('task',run.id);}}/>;
 return <Modal title={workflow==='specification'?'生成需求文档':'运行需求分析'} close={close}><div className="form-fields">{isLoading?<Loading/>:<><p>{requirement?'已关联：'+requirement.number+' '+requirement.title:'选择技能后填写任务和资料，生成完成进入正文编辑。'}</p><label>使用技能<SearchSelect aria-label="使用技能" value={selected?.id||''} onChange={event=>setId(event.target.value)}>{available.map(skill=><option key={skill.id} value={skill.id}>{skill.name} · {skill.public?'公共':'个人'}</option>)}</SearchSelect></label><p className="muted">{selected?.description||'暂无可用技能，请在技能库创建或导入。'}</p></>}</div><footer><button className="secondary" onClick={close}>取消</button><button className="primary" disabled={!selected} onClick={()=>setStart(true)}>继续填写任务</button></footer></Modal>;
}
