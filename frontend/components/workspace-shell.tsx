'use client';
import {useState,useEffect,useRef} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {LayoutDashboard,MessageSquare,CalendarCheck2,Library,Sparkles,ShieldCheck,Settings2,Plus,LogOut,Moon,Sun,Bell,PanelLeftClose,PanelLeftOpen} from 'lucide-react';
import {api,date} from '../lib/api';
import {roleNames} from '../lib/roles';
import {refreshAtHome} from '../lib/auth-navigation';
import {useWorkspaceNavigation,type WorkspaceRoute} from '../lib/workspace-navigation';
import type {User,Conversation,Notification,Version} from '../lib/types';
import type {Destination} from '../lib/journey';
import {AuthPage,PageKey} from './workbench';
import {useNavigationGuard} from './navigation-guard';
import {useAction,Loading,Modal,FormModal} from './ui';
import {DashboardPage} from './dashboard';
import {ClarificationPage,RequirementsPage} from './business';
import {KnowledgePage,DocumentPanel} from './knowledge';
import {SkillsPage,ChatPage,RunPage} from './chat';
import {ReviewsPage,AdminPage} from './governance';
import {RequirementWorkspace} from './requirement-workspace';
import {DocumentWorkspacePage} from './document-workspace';
import {ProcessingTaskPage} from './processing-tasks';
import {GenerationLauncher} from './generation-launcher';
const pages:{key:PageKey;label:string;icon:typeof LayoutDashboard;role?:string}[]=[{key:'dashboard',label:'工作台首页',icon:LayoutDashboard},{key:'chat',label:'知识问答',icon:MessageSquare},{key:'requirements',label:'需求分析与关联',icon:Sparkles},{key:'clarification',label:'需求澄清计划',icon:CalendarCheck2},{key:'knowledge',label:'需求知识库',icon:Library},{key:'skills',label:'技能库',icon:Sparkles},{key:'reviews',label:'审核工作台',icon:ShieldCheck},{key:'admin',label:'系统管理',icon:Settings2,role:'super_admin'}];
const allowed=new Set([...pages.map(p=>p.key),'run','requirement','document','generate','editor','task']);
const developmentPages = new Set<PageKey>(['knowledge','requirements','requirement','task','document','chat']);
function defaultReturn(route:WorkspaceRoute):WorkspaceRoute|undefined {
 switch(route.page){
  case 'requirement':return {page:'requirements',id:'business'};
  case 'task':return {page:'requirements',id:'tasks'};
  case 'editor':return route.id.startsWith('run~')?{page:'task',id:route.id.slice(4)}:{page:'knowledge',id:''};
  case 'run':return {page:'skills',id:''};
  case 'document':return {page:'knowledge',id:''};
  case 'reviews':return route.id?{page:'reviews',id:''}:undefined;
  case 'generate':return {page:'dashboard',id:''};
 }
}
function returnLabel(route:WorkspaceRoute):string {
 if(route.page==='requirements'){
  const tab=route.tab||route.id;
  return '返回'+(tab==='tasks'?'任务列表':tab==='relations'?'关联清单':tab==='graph'?'关联图':'需求列表');
 }
 const labels:Partial<Record<PageKey,string>>={requirement:'需求详情',task:'任务详情',editor:'文档编辑工作台',run:'执行过程',document:'文档版本',knowledge:'文档列表',reviews:route.id?'审核详情':'审核列表'};
 return '返回'+(labels[route.page]||pages.find(page=>page.key===route.page)?.label||'工作台首页');
}
export function WorkspaceShell(){
 const queryClient=useQueryClient();const account=useRef<string|undefined>(undefined);
 const guard=useNavigationGuard();const {request}=guard;
 const {route,previous,open,setTab,back}=useWorkspaceNavigation(allowed,guard);
 const {data:user,isLoading}=useQuery({queryKey:['user'],queryFn:()=>api<User>('/auth/me')});const [collapsed,setCollapsed]=useState(false);const [dark,setDark]=useState(false);const [showNew,setShowNew]=useState(false);const [profile,setProfile]=useState(false);const [alerts,setAlerts]=useState(false);const [changePassword,setChangePassword]=useState(false);const [historySearch,setHistorySearch]=useState('');const [showArchived,setShowArchived]=useState(false);const {perform}=useAction();
 const {data:history=[]}=useQuery({queryKey:['conversations',showArchived],queryFn:()=>api<Conversation[]>('/conversations?include_archived='+showArchived),enabled:!!user});const {data:notifications=[]}=useQuery({queryKey:['notifications'],queryFn:()=>api<Notification[]>('/notifications'),enabled:!!user,refetchInterval:30000});
 const readOnly=user?.role==='development_member';
 function canOpen(page:PageKey){return (page!=='admin'||user?.role==='super_admin')&&(!readOnly||developmentPages.has(page));}
 function navigate(page:PageKey,id='',replace=false){
  if(!canOpen(page))return;
  if(replace&&previous?.page===page&&previous.id===id)back({page,id},true);
  else request(()=>open({page,id},replace));
 }
 function openTaskResult(id:string,tab='analysis'){request(()=>open({page:'task',id,tab}));}
 function openRequirementAnalysis(id:string){request(()=>open({page:'requirement',id,tab:'analysis'}));}
 function destination(target:Destination){navigate(target.page as PageKey,target.page==='document'?target.document_id+'~'+target.id:target.id);}
 useEffect(()=>{globalThis.document.documentElement.dataset.theme=dark?'dark':'light';},[dark]);
 useEffect(()=>{if(account.current!==user?.id){if(account.current!==undefined)queryClient.removeQueries({predicate:query=>query.queryKey[0]!=='user'});account.current=user?.id;}},[user?.id,queryClient]);
 async function newChat(){request(()=>{void perform(()=>api<Conversation>('/conversations','POST'),'已创建知识问答').then(chat=>{if(chat)open({page:'chat',id:chat.id});});});}
 useEffect(()=>{if(readOnly&&!developmentPages.has(route.page))open({page:'chat',id:''},true);},[readOnly,route.page]);
 if(isLoading)return <Loading/>;if(!user)return <AuthPage/>;
 if(readOnly&&!developmentPages.has(route.page))return <Loading/>;
 const fallback=defaultReturn(route);
 const source=previous&&canOpen(previous.page)?previous:undefined;
 const label=fallback?returnLabel(source||fallback):undefined;
 const goBack=()=>{if(fallback)back(fallback,Boolean(source));};
 const title=route.page==='task'?'处理任务详情':route.page==='editor'?'文档编辑工作台':route.page==='requirement'?'需求详情':route.page==='document'?'文档版本':route.page==='run'?'文档生成与编辑':route.page==='generate'?'生成需求文档':pages.find(p=>p.key===route.page)?.label;
 return <div className={'app-shell '+(collapsed?'collapsed':'')}><aside className="sidebar"><div className="brand"><span className="brand-icon"><Sparkles size={21}/></span>{!collapsed&&<div><strong>需求智能工作台</strong><small>AGENTIC WORKBENCH</small></div>}</div><button className="new-chat" onClick={()=>readOnly?void newChat():setShowNew(true)}><Plus size={18}/>{!collapsed&&(readOnly?'新问答':'开启新工作')}</button><nav>{pages.filter(p=>(!p.role||user.role===p.role)&&(!readOnly||developmentPages.has(p.key))).map(p=><button title={p.label} key={p.key} className={route.page===p.key||['requirement','task'].includes(route.page)&&p.key==='requirements'?'active':''} onClick={()=>navigate(p.key)}><p.icon size={19}/>{!collapsed&&<span>{p.key==='reviews'&&user.role==='requirement_member'?'我的审核申请':p.label}</span>}</button>)}</nav>{!collapsed&&route.page!=='chat'&&<button className="text-button" onClick={()=>navigate('chat')}>历史问答 →</button>}{!collapsed&&route.page==='chat'&&<section className="history"><strong className="history-heading">历史问答</strong><button className="text-button small" onClick={()=>setShowArchived(!showArchived)}>{showArchived?'隐藏已归档':'查看已归档'}</button><input aria-label="搜索历史问答" placeholder="搜索历史问答" value={historySearch} onChange={e=>setHistorySearch(e.target.value)}/>{history.filter(c=>c.title.toLowerCase().includes(historySearch.toLowerCase())).map(c=><div className="history-row" key={c.id}><button onClick={()=>navigate('chat',c.id)}><MessageSquare size={14}/><span>{c.title}{c.archived?'（已归档）':''}</span></button><button title={c.archived?'恢复':'归档'} onClick={()=>void perform(()=>api('/conversations/'+c.id,'PATCH',{archived:!c.archived}))}>{c.archived?'↶':'×'}</button></div>)}</section>}<div className="sidebar-bottom"><button className="user-profile" onClick={()=>setProfile(true)}><span className="avatar">{user.display_name[0]}</span>{!collapsed&&<div><strong>{user.display_name}</strong><small>{roleNames[user.role]}</small></div>}</button><button className="collapse-button" onClick={()=>setCollapsed(!collapsed)}>{collapsed?<PanelLeftOpen size={18}/>:<><PanelLeftClose size={18}/><span>收起导航</span></>}</button></div></aside><div className="main-shell"><header className="topbar"><div className="breadcrumb">工作空间 <span>/</span><strong>{title}</strong></div><div className="top-actions"><button className="icon-button" aria-label="切换主题" onClick={()=>setDark(!dark)}>{dark?<Sun size={19}/>:<Moon size={19}/>}</button><button className="icon-button notification-button" aria-label="通知" onClick={()=>setAlerts(true)}><Bell size={19}/>{notifications.some(n=>!n.read)&&<i/>}</button><span className="avatar small-avatar">{user.display_name[0]}</span></div></header><main className="page-content">{label&&<div className="subpage-return"><button className="secondary" onClick={goBack}>{label}</button></div>}
 {route.page==='dashboard'&&<DashboardPage user={user} navigate={navigate} newChat={async()=>setShowNew(true)}/>}{route.page==='requirements'&&<RequirementsPage user={user} navigate={navigate} initialRequirementId={route.id} activeTab={route.tab} onTabChange={setTab}/>}{route.page==='requirement'&&<RequirementWorkspace key={route.id} user={user} id={route.id} navigate={navigate} activeTab={route.tab} activePackId={route.pack} onTabChange={setTab} openTaskResult={openTaskResult}/>}{route.page==='skills'&&<SkillsPage user={user} navigate={navigate}/>}{route.page==='task'&&<ProcessingTaskPage key={route.id} user={user} id={route.id} navigate={navigate} activeTab={route.tab} onTabChange={setTab} openRequirementAnalysis={openRequirementAnalysis}/>}{route.page==='editor'&&<DocumentWorkspacePage key={route.id} user={user} id={route.id} navigate={navigate}/>}{route.page==='run'&&<RunPage key={route.id} user={user} runId={route.id} navigate={navigate} openTaskResult={openTaskResult}/>}{route.page==='clarification'&&<ClarificationPage user={user} navigate={navigate} activeTab={route.tab} onTabChange={setTab}/>}{route.page==='knowledge'&&<KnowledgePage user={user}/>}{route.page==='chat'&&<ChatPage key={route.id} user={user} conversationId={route.id} setConversationId={id=>navigate('chat',id)} navigate={navigate}/>}{route.page==='reviews'&&<ReviewsPage key={route.id} user={user} initialReviewId={route.id} closeDetail={goBack} returnLabel={label}/>}{route.page==='admin'&&user.role==='super_admin'&&<AdminPage user={user}/>}{route.page==='document'&&<><div className="page-heading"><h1>文档版本与审核</h1></div><DocumentDestination key={route.id} user={user} id={route.id} close={goBack} returnLabel={label}/></>}{route.page==='generate'&&<GenerationLauncher close={goBack} navigate={navigate}/>}
 </main><div className="app-footer">需求智能工作台 <span>知识溯源 · 需求分析 · 协作交付</span></div></div>
 {showNew&&<Modal title="开启新工作" close={()=>setShowNew(false)}><div className="work-intents">{[{title:'新建业务需求',detail:'登记需求背景和资料',page:'requirements',id:'new'},{title:'生成需求文档',detail:'选择技能，生成后进入人工 / AI 编辑',page:'generate',id:''},{title:'知识问答',detail:'检索资料，开展多轮讨论',page:'chat',id:''},{title:'继续未完成工作',detail:'返回首页查看待确认、编辑和审核任务',page:'dashboard',id:''}].map(item=><button key={item.title} onClick={()=>{setShowNew(false);if(item.page==='chat')void newChat();else navigate(item.page as PageKey,item.id);}}><strong>{item.title}</strong><span>{item.detail}</span></button>)}</div></Modal>}
 {profile&&<Modal title="个人设置" close={()=>setProfile(false)}><div className="form-fields"><p>{user.display_name}　@{user.username}</p><button className="secondary" onClick={()=>setChangePassword(true)}>修改密码</button><button className="secondary" onClick={()=>request(()=>{setProfile(false);void perform(async()=>{await api('/auth/logout','POST');refreshAtHome();return true;},'已退出登录');})}><LogOut size={16}/>退出登录</button></div></Modal>}
 {changePassword&&<FormModal title="修改密码" close={()=>setChangePassword(false)} fields={[{key:'current_password',label:'原密码',type:'password',required:true},{key:'password',label:'新密码（至少6位）',type:'password',required:true}]} onSubmit={values=>perform(async()=>{await api('/auth/password','POST',values);refreshAtHome();return true;},'密码已修改，请重新登录')}/>}
 {alerts&&<Modal title="通知" close={()=>setAlerts(false)}><div className="notification-list">{notifications.map(n=><button key={n.id} onClick={async()=>{await perform(()=>api('/notifications/'+n.id+'/read','POST'),'已读');if(n.destination){setAlerts(false);destination(n.destination);}}}><strong>{n.message}</strong><small>{date(n.created_at)} · {n.read?'已读':'未读'}{n.destination?' · 点击继续处理':''}</small></button>)}{!notifications.length&&<p>暂无通知</p>}</div></Modal>}</div>;
}

function DocumentDestination({user,id,close,returnLabel}:{user:User;id:string;close:()=>void;returnLabel?:string}){const [documentId,versionId]=id.split('~');const {data:versions,error}=useQuery({queryKey:['versions',documentId],queryFn:()=>api<Version[]>('/documents/'+documentId+'/versions'),enabled:!versionId});const current=versionId||versions?.[0]?.id;if(!current)return error?<p className="form-error">{error.message}</p>:<Loading/>;return <DocumentPanel user={user} documentId={documentId} initialVersionId={current} close={close} returnLabel={returnLabel}/>;}
