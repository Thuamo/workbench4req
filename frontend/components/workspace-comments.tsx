'use client';

import {useEffect,useMemo,useRef,useState,type RefObject} from 'react';
import {commentRange,indexCommentText,locateComment,type CommentTarget} from '../lib/comment-anchor';
import {CommentCard,CommentForm,type Comment} from './document-comments';
import {Loading} from './ui';

const spacing=10;
const draftId='draft';
type Placement={id:string;gap:number;located:boolean};

export function WorkspaceComments({endpoint,userId,visible,comments,isLoading,error,manuscript,draft,setDraft,beforeAdd}: {
  endpoint: string;
  userId: string;
  visible: boolean;
  comments: Comment[]|undefined;
  isLoading: boolean;
  error: Error|null;
  manuscript: RefObject<HTMLElement|null>;
  draft: CommentTarget|null;
  setDraft: (target: CommentTarget|null) => void;
  beforeAdd: () => Promise<boolean>;
}) {
  const list=useRef<HTMLOListElement>(null);
  const [placements,setPlacements]=useState<Placement[]>([]);
  const entries=useMemo(()=>[...(draft?[{id:draftId,target:draft}]:[]),...(comments||[]).map(comment=>({id:comment.id,target:comment,comment}))],[comments,draft]);

  useEffect(()=>{
    const root=manuscript.current?.querySelector<HTMLElement>('.tiptap');
    const notes=list.current;
    if (!visible || !root || !notes || !entries.length) return;
    const cards=Array.from(notes.querySelectorAll<HTMLElement>('[data-comment-note]'));
    let frame=0;

    function measure() {
      const index=indexCommentText(root!);
      const top=notes!.getBoundingClientRect().top;
      const heights=new Map(cards.map(card=>[card.dataset.commentNote,Math.ceil(card.getBoundingClientRect().height)]));
      const sorted=entries.map(entry=>{
        const range=commentRange(index,entry.target);
        const rect=range?.getClientRects()[0];
        const desired=rect?Math.ceil(rect.top-top):entry.id===draftId ? 0 : Infinity;
        return {id:entry.id,desired,located:Boolean(rect)};
      }).sort((a,b)=>a.desired===b.desired?0:a.desired-b.desired);
      let nextTop=0;
      const next=sorted.map(({id,desired,located})=>{
        const gap=Number.isFinite(desired)?Math.max(0,desired-nextTop):0;
        nextTop+=gap+(heights.get(id)||0)+spacing;
        return {id,gap,located};
      });
      setPlacements(previous=>JSON.stringify(previous)===JSON.stringify(next)?previous:next);
    }

    function schedule() {cancelAnimationFrame(frame);frame=requestAnimationFrame(measure);}
    const resize=new ResizeObserver(schedule);
    const mutations=new MutationObserver(schedule);
    resize.observe(root);resize.observe(notes);
    for (const card of cards) resize.observe(card);
    mutations.observe(root,{subtree:true,characterData:true,childList:true});
    schedule();
    return ()=>{cancelAnimationFrame(frame);resize.disconnect();mutations.disconnect();};
  },[entries,manuscript,visible]);

  const draftPlacement=placements.find(item=>item.id===draftId);
  useEffect(()=>{
    if (!draft || !draftPlacement || !visible) return;
    const input=list.current?.querySelector<HTMLTextAreaElement>('textarea');
    if (!input) return;
    const frame=requestAnimationFrame(()=>{
      const rect=input.getBoundingClientRect();
      if (document.activeElement===input && (rect.top<64 || rect.bottom>window.innerHeight)) input.scrollIntoView({block:'nearest'});
    });
    return ()=>cancelAnimationFrame(frame);
  },[draft,draftPlacement,visible]);

  const placed=new Map(placements.map((item,index)=>[item.id,{...item,index}]));
  const sorted=[...entries].sort((a,b)=>(placed.get(a.id)?.index??Infinity)-(placed.get(b.id)?.index??Infinity));
  return <aside className="workspace-comment-rail document-comments" aria-label="批注栏" id="workspace-comments" hidden={!visible}>
    <h3>批注栏</h3>
    {visible&&isLoading?<Loading/>:error?<p className="form-error">{error.message}</p>:!entries.length&&<p className="muted">选中正文后点击「批注」。</p>}
    <ol className="workspace-comment-notes" ref={list}>
      {sorted.map(entry=>{
        const placement=placed.get(entry.id);
        return <li key={entry.id} data-comment-note={entry.id} style={{marginTop:placement?.gap||0}}>
          {'comment' in entry?<CommentCard comment={entry.comment} endpoint={endpoint} userId={userId}
            unlocated={Boolean(entry.comment.quote&&placement&&!placement.located)}
            locate={()=>locateComment(manuscript.current?.querySelector<HTMLElement>('.tiptap')||null,entry.target)}/>
            :<div className="workspace-comment-draft"><CommentForm endpoint={endpoint} target={entry.target} beforeAdd={beforeAdd}
              makeWhole={()=>setDraft({quote:''})} afterAdd={()=>setDraft(null)} cancel={()=>setDraft(null)} focus={visible}/></div>}
        </li>;
      })}
    </ol>
  </aside>;
}
