'use client';

import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {api,date} from '../lib/api';
import {locateComment,selectedCommentTarget,type CommentTarget} from '../lib/comment-anchor';
import {Loading,Modal,useAction} from './ui';

export type Comment = CommentTarget & {
  id: string;
  author_id: string;
  author_name: string;
  content: string;
  created_at: string;
  workspace_id: string | null;
};

export function useDocumentComments(endpoint: string, visible = true) {
  return useQuery({queryKey:['document-comments',endpoint],queryFn:()=>api<Comment[]>(endpoint),enabled:visible,refetchInterval:5000});
}

export function CommentCard({comment,endpoint,userId,locate,unlocated=false}: {
  comment: Comment; endpoint: string; userId: string; locate: () => boolean; unlocated?: boolean;
}) {
  const {perform} = useAction();
  const [notice,setNotice] = useState('');
  return <article className="document-comment">
    <div className="button-group"><strong>{comment.author_name}</strong><small className="muted">{date(comment.created_at)}{comment.workspace_id?' · 当前草稿':''}</small></div>
    {comment.quote?<blockquote>{comment.quote}</blockquote>:<small className="muted">整篇文档</small>}
    {unlocated && <small className="muted">原文待定位</small>}
    <p>{comment.content}</p>
    <div className="button-group">
      {comment.quote && <button type="button" className="text-button" onClick={()=>setNotice(locate()?'':'当前正文中未找到唯一对应的原文。')}>定位原文</button>}
      {userId===comment.author_id && <button type="button" className="text-button" onClick={()=>void perform(()=>api(endpoint+'/'+comment.id,'DELETE'),'批注已删除')}>删除批注</button>}
    </div>
    {notice && <p role="status" className="muted">{notice}</p>}
  </article>;
}

export function CommentForm({endpoint,target,beforeAdd,afterAdd,makeWhole,cancel,focus=false}: {
  endpoint: string; target: CommentTarget; beforeAdd?: () => Promise<boolean>; afterAdd: () => void;
  makeWhole: () => void; cancel?: () => void; focus?: boolean;
}) {
  const [text,setText] = useState('');
  const [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState('');
  const {perform} = useAction();
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{if(focus)input.current?.focus({preventScroll:true});},[target,focus]);

  async function submit() {
    if (busy || !text.trim()) return;
    setBusy(true);
    setNotice('');
    try {
      if (beforeAdd && !(await beforeAdd())) {
        setNotice('草稿未保存，请先处理编辑器中的保存错误。');
        return;
      }
      const saved=await perform(()=>api<Comment>(endpoint,'POST',{...target,content:text}),'批注已添加');
      if (saved) {setText('');afterAdd();}
    } finally {setBusy(false);}
  }

  return <form onSubmit={event=>{event.preventDefault();void submit();}}>
    {target.quote?<div><blockquote>{target.quote}</blockquote><button type="button" className="text-button" onClick={makeWhole}>改为整篇批注</button></div>:<small className="muted">整篇文档</small>}
    {notice && <p role="status" className="notice">{notice}</p>}
    <label>批注内容<textarea ref={input} value={text} maxLength={4000} rows={3} required onChange={event=>setText(event.target.value)}/></label>
    <div className="button-group">{cancel&&<button type="button" className="secondary" disabled={busy} onClick={cancel}>取消</button>}
      <button className="primary" disabled={busy||!text.trim()}>{busy?'正在添加…':'添加批注'}</button></div>
  </form>;
}

function DocumentComments({endpoint,userId,initialTarget,close,locate,readOnly}: {
  endpoint: string; userId: string; initialTarget: CommentTarget; close: () => void; locate: (target: CommentTarget) => boolean; readOnly: boolean;
}) {
  const [target,setTarget] = useState(initialTarget);
  const {data=[],isLoading,error} = useDocumentComments(endpoint);
  return <Modal title="文档批注" close={close}>
    <div className="form-fields document-comments">
      {isLoading?<Loading/>:error?<p className="form-error">{error.message}</p>:!data.length&&<p className="muted">暂无批注</p>}
      {data.map(comment=><CommentCard key={comment.id} comment={comment} endpoint={endpoint} userId={readOnly?'':userId} locate={()=>{
        if (!locate(comment)) return false;
        close();return true;
      }}/>) }
      {!readOnly&&<CommentForm endpoint={endpoint} target={target} makeWhole={()=>setTarget({quote:''})} afterAdd={()=>setTarget({quote:''})}/>}
    </div>
  </Modal>;
}

export function SpecificationPreview({content,versionId,userId,className,readOnly=false,children}: {
  content: string; versionId: string; userId: string; className: string; readOnly?: boolean; children?: ReactNode;
}) {
  const body=useRef<HTMLElement>(null);
  const [target,setTarget]=useState<CommentTarget|null>(null);
  return <>
    <button type="button" className="secondary" onMouseDown={event=>event.preventDefault()} onClick={()=>setTarget(selectedCommentTarget(body.current))}>{readOnly?'查看批注':'批注'}</button>
    <article ref={body} className={className}>{children??<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>}</article>
    {target&&<DocumentComments endpoint={'/versions/'+versionId+'/comments'} userId={userId} initialTarget={target} close={()=>setTarget(null)} locate={comment=>locateComment(body.current,comment)} readOnly={readOnly}/>}
  </>;
}
