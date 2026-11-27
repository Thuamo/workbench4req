'use client';

import {useEffect,useRef,useState} from 'react';
import type {PageKey} from '../components/workbench';

export type WorkspaceRoute={page:PageKey;id:string;tab?:string;pack?:string};
type Entry={route:WorkspaceRoute;previous?:WorkspaceRoute;trail:string;position:number};
type Guard={request:(action:()=>void)=>void;isDirty:()=>boolean};
const home:WorkspaceRoute={page:'dashboard',id:''};
const routeTabs:Partial<Record<PageKey,readonly string[]>>={
  requirements:['business','tasks','relations','graph'],
  requirement:['overview','tasks','documents','materials','analysis','history',
    'clarification-tasks','clarification-documents','clarification-analysis',
    'specification-tasks','specification-documents','specification-history',
    'consolidation-tasks','consolidation-documents'],
  clarification:['tasks','stats'],
  task:['overview','documents','analysis','process','requirements'],
};

function routeHash({page,id,tab,pack}:WorkspaceRoute){
  return '#'+new URLSearchParams({page,...(id?{id}:{}),...(tab?{tab}:{}),...(pack?{pack}:{})});
}

function readRoute(allowed:ReadonlySet<string>):WorkspaceRoute{
  const params=new URLSearchParams(location.hash.slice(1));
  const page=params.get('page');
  if(!page||!allowed.has(page))return home;
  const key=page as PageKey;
  const tab=params.get('tab');
  return {page:key,id:params.get('id')||'',tab:tab&&routeTabs[key]?.includes(tab)?tab:undefined,
    pack:key==='requirement'?params.get('pack')||undefined:undefined};
}

function newEntry(route:WorkspaceRoute):Entry {
  return {route,trail:Date.now().toString(36)+Math.random().toString(36).slice(2),position:0};
}

function readEntry(route:WorkspaceRoute):Entry|undefined {
  const entry=history.state?.workbench as Entry|undefined;
  if(entry?.route&&routeHash(entry.route)===routeHash(route)&&typeof entry.trail==='string'&&Number.isInteger(entry.position))return entry;
}

function writeEntry(entry:Entry,replace:boolean){
  const state={...history.state,workbench:entry};
  if(replace)history.replaceState(state,'',routeHash(entry.route));
  else history.pushState(state,'',routeHash(entry.route));
}

export function useWorkspaceNavigation(allowed:ReadonlySet<string>,guard:Guard){
  const [entry,setEntry]=useState<Entry|null>(null);
  const current=useRef<Entry|null>(null);
  const restoring=useRef<{entry:Entry;delta:number}|null>(null);
  const guardRef=useRef(guard);guardRef.current=guard;

  function show(next:Entry,scroll=true){
    current.current=next;
    setEntry(next);
    if(scroll)window.scrollTo({top:0});
  }

  useEffect(()=>{
    const route=readRoute(allowed);
    const first=readEntry(route)||newEntry(route);
    writeEntry(first,true);
    show(first);

    function onHistoryChange(){
      const displayed=current.current;
      if(!displayed)return;
      const nextRoute=readRoute(allowed);
      const next=readEntry(nextRoute);
      const rollback=restoring.current;
      if(rollback){
        if(next?.trail===rollback.entry.trail&&next.position===rollback.entry.position){
          restoring.current=null;
          guardRef.current.request(()=>history.go(rollback.delta));
        }
        return;
      }
      if(next?.trail===displayed.trail&&next.position===displayed.position&&routeHash(next.route)===routeHash(displayed.route))return;
      if(next?.trail===displayed.trail&&guardRef.current.isDirty()){
        const delta=next.position-displayed.position;
        if(delta){
          // Return to the editor before showing the guard, preserving both history entries.
          restoring.current={entry:displayed,delta};
          history.go(-delta);
          return;
        }
      }
      if(guardRef.current.isDirty()){
        // A manually entered hash may have no position in the workbench history.
        const restored=newEntry(displayed.route);
        writeEntry(restored,true);
        show(restored,false);
        guardRef.current.request(()=>{const destination=newEntry(nextRoute);writeEntry(destination,true);show(destination);});
      }else{
        const destination=next||newEntry(nextRoute);
        if(!next)writeEntry(destination,true);
        show(destination);
      }
    }
    window.addEventListener('popstate',onHistoryChange);
    window.addEventListener('hashchange',onHistoryChange);
    return()=>{window.removeEventListener('popstate',onHistoryChange);window.removeEventListener('hashchange',onHistoryChange);};
  },[allowed]);

  function open(route:WorkspaceRoute,replace=false){
    const displayed=current.current;
    if(displayed&&routeHash(displayed.route)===routeHash(route))return;
    const next=displayed?(replace?{...displayed,route}:{route,trail:displayed.trail,position:displayed.position+1,previous:displayed.route}):newEntry(route);
    writeEntry(next,replace);
    show(next);
  }

  function setTab(tab:string,pack?:string){
    const displayed=current.current;
    if(!displayed||!routeTabs[displayed.route.page]?.includes(tab))return;
    const selectedPack=pack??displayed.route.pack;
    if(displayed.route.tab===tab&&displayed.route.pack===selectedPack)return;
    const next={...displayed,route:{...displayed.route,tab,pack:selectedPack}};
    writeEntry(next,true);
    show(next,false);
  }

  function back(fallback:WorkspaceRoute,usePrevious:boolean){
    guardRef.current.request(()=>{
      if(usePrevious)history.back();
      else open(fallback,true);
    });
  }

  return {route:entry?.route||home,previous:entry?.previous,open,setTab,back};
}
