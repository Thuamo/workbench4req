'use client';
import {useQuery} from '@tanstack/react-query';
import {api,states} from '../lib/api';
import type {Question,Task} from '../lib/types';
import {FormModal,useAction} from './ui';

export function RequirementQuestionForm({requirementId,packId,question,close}:{requirementId:string;packId?:string;question?:Question;close:()=>void}){
  const {perform}=useAction();
  const {data:tasks=[]}=useQuery({queryKey:['tasks'],queryFn:()=>api<Task[]>('/clarification/tasks'),select:items=>items.filter(item=>item.can_edit)});
  const endpoint=question?'/clarification/questions/'+question.id:'/clarification/questions';
  return <FormModal title={question?'反馈与确认澄清结论':'新增澄清问题'} initial={question||{category:'业务规则',status:'open'}} close={close}
    fields={[
      {key:'description',label:'问题描述',type:'textarea',required:true},
      {key:'category',label:'分类',required:true},
      {key:'reason',label:'原因',type:'textarea'},
      {key:'target',label:'澄清对象'},
      {key:'task_id',label:'关联台账',type:'select',options:tasks.map(task=>({value:task.id,label:[task.fields['需求编号'],task.fields['需求名称']].filter(Boolean).join(' · ')}))},
      {key:'feedback',label:'业务反馈',type:'textarea'},
      {key:'conclusion',label:'确认结论',type:'textarea'},
      {key:'status',label:'状态',type:'select',options:['open','answered','confirmed','rejected'].map(value=>({value,label:states[value]})),required:true},
    ]}
    onSubmit={values=>perform(()=>api(endpoint,question?'PATCH':'POST',{
      ...values,requirement_id:requirementId,task_id:values.task_id||null,
      evidence:question?.evidence||(packId?{requirement_pack_id:packId}:{}),
    }))}/>;
}
