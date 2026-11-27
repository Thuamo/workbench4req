'use client';
import { useState, useEffect } from 'react';
import {WorkspaceShell} from './workspace-shell';
import {NavigationGuard} from './navigation-guard';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { LayoutDashboard, MessageSquare, CalendarCheck2, Library, Sparkles, ShieldCheck, Settings2, PanelLeftClose, PanelLeftOpen, Plus, Moon, Sun, LogOut, Network, Bell, Search, ChevronDown, ArrowRight, Fingerprint, BookOpen, FileCheck2 } from 'lucide-react';
import { api, date } from '../lib/api';
import {refreshAtHome} from '../lib/auth-navigation';
import type { User, Conversation, Notification } from '../lib/types';
import { ActionProvider, useAction, Loading, FormModal, JsonView, Modal } from './ui';
import { DashboardPage } from './dashboard';
import { KnowledgePage } from './knowledge';
import { ClarificationPage, RequirementsPage } from './business';
import { SkillsPage, ChatPage, RunPage } from './chat';
import { ReviewsPage, AdminPage } from './governance';

export function Workbench() {const [client]=useState(()=>new QueryClient({defaultOptions:{queries:{retry:false,staleTime:10000,refetchOnWindowFocus:false}}}));return <QueryClientProvider client={client}><ActionProvider><NavigationGuard><WorkspaceShell/></NavigationGuard></ActionProvider></QueryClientProvider>;}
const authSchema=z.object({username:z.string().min(3,'用户名至少3位'),display_name:z.string(),password:z.string().min(6,'密码至少6位'),confirm_password:z.string()});
type AuthForm=z.infer<typeof authSchema>;
export function AuthPage() {
 const [register,setRegister]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const {perform}=useAction();
 const {register:field,handleSubmit,formState:{errors}}=useForm<AuthForm>({resolver:zodResolver(authSchema),defaultValues:{username:'',display_name:'',password:'',confirm_password:''}});
 return <main className="auth-page"><section className="auth-story"><div className="brand"><span className="brand-icon"><Sparkles size={23}/></span><strong>需求智能工作台</strong></div><div><span className="eyebrow">REQUIREMENTS ENGINEERING</span><h1>让每一条需求，<br/>都有据可循。</h1><p>连接业务知识、需求分析与文档交付，<br/>让团队在同一个工作台中协作。</p><div className="auth-flow">{[[BookOpen,'知识沉淀'],[Network,'影响分析'],[FileCheck2,'审核交付']].map(([Icon,label],i)=>{const I=Icon as typeof BookOpen;return <div key={i}><I size={22}/><span>{label as string}</span>{i<2&&<ArrowRight size={15}/>}</div>;})}</div></div><small>版本可追溯 · 人工会签 · 来源可核验</small></section><section className="auth-card"><span className="auth-symbol"><Fingerprint size={34}/></span><h2>{register?'创建您的账号':'欢迎回来'}</h2><p>{register?'注册后默认加入需求组。':'登录后继续您的需求工作。'}</p><form onSubmit={handleSubmit(async values=>{setError('');setBusy(true);try{if(register){if(!values.display_name.trim())throw new Error('请填写显示名称');await api('/auth/register','POST',values);}await api('/auth/login','POST',{username:values.username,password:values.password});refreshAtHome();}catch(e){setError(e instanceof Error?e.message:'登录失败');}finally{setBusy(false);}})}><label>用户名<input autoComplete="username" {...field('username')}/><small className="form-error">{errors.username?.message}</small></label>{register&&<label>显示名称<input {...field('display_name')}/></label>}<label>密码<input type="password" autoComplete={register?'new-password':'current-password'} {...field('password')}/><small className="form-error">{errors.password?.message}</small></label>{register&&<label>确认密码<input type="password" autoComplete="new-password" {...field('confirm_password')}/></label>}{error&&<p className="form-error">{error}</p>}<button className="primary" disabled={busy}>{busy?'处理中…':register?'注册并登录':'登录工作台'}<ArrowRight size={17}/></button></form><div className="auth-switch">{register?'已有账号？':'还没有账号？'}<button onClick={()=>{setRegister(!register);setError('');}}>{register?'立即登录':'注册账号'}</button></div></section></main>;
}

export type PageKey='dashboard'|'chat'|'clarification'|'knowledge'|'skills'|'reviews'|'admin'|'requirements'|'run'|'requirement'|'document'|'generate'|'editor'|'task';
function PasswordForm({close}:{close:()=>void}){const [open,setOpen]=useState(false);const {perform}=useAction();return <><button className="secondary" onClick={()=>setOpen(true)}>修改密码</button>{open&&<FormModal title="修改密码" fields={[{key:'current_password',label:'原密码',type:'password',required:true},{key:'password',label:'新密码（至少6位）',type:'password',required:true}]} close={()=>setOpen(false)} onSubmit={data=>perform(async()=>{const result=await api('/auth/password','POST',data);refreshAtHome();return result;},'密码已修改，请重新登录')}/>}</>;}
