'use client';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useEditor,EditorContent,type JSONContent} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {TableKit} from '@tiptap/extension-table';
import {Markdown,MarkdownManager} from '@tiptap/markdown';
import {DOMParser,Fragment,Slice} from '@tiptap/pm/model';
import {NodeSelection,Selection,type Transaction} from '@tiptap/pm/state';
import {DocumentImage,type SpecificationImage} from '../lib/document-image';
import {DocumentAlignment,alignments,editorContent} from '../lib/document-alignment';
import {clipboardImages,clipboardMarkup,clipboardTextTable,imageFromClipboardElement,normalizeClipboardTables,validateClipboardImage} from '../lib/document-clipboard';

export type HeadingEntry={text:string;level:number;position:number;blockFrom:number};
const workspaceExtensions=[StarterKit.configure({heading:{levels:[1,2,3]},link:{openOnClick:false,autolink:false}}),
 TableKit.configure({table:{resizable:false}}),DocumentImage,DocumentAlignment,Markdown];

export function parseWorkspaceMarkdown(value:string):JSONContent {
 return new MarkdownManager({extensions:workspaceExtensions}).parse(value);
}

export function RichTextEditor({value,onChange,onOutline,onSelection,onSelectionRange,uploadImage,onImageUploadChange,onComment,sidePanel,showSidePanel,label='文档正文',readOnly=false}:{value:JSONContent|string;onChange?:(value:JSONContent)=>void;onOutline?:(entries:HeadingEntry[])=>void;onSelection?:(text:string)=>void;onSelectionRange?:(range:{from:number;to:number}|null)=>void;uploadImage?:(file:File)=>Promise<SpecificationImage>;onImageUploadChange?:(uploading:boolean)=>void;onComment?:()=>void;sidePanel?:ReactNode;showSidePanel?:boolean;label?:string;readOnly?:boolean}){
 const frame=useRef<HTMLDivElement>(null);
 const imageInput=useRef<HTMLInputElement>(null);
 const [uploading,setUploading]=useState(false);
 const uploadingRef=useRef(false);
 const [imageError,setImageError]=useState('');
 const paste=useRef<(event:ClipboardEvent)=>boolean>(()=>false);

 const callbacks=useRef({onChange,onOutline,onSelection,onSelectionRange});callbacks.current={onChange,onOutline,onSelection,onSelectionRange};
 const editor=useEditor({extensions:workspaceExtensions,immediatelyRender:false,shouldRerenderOnTransaction:true,content:value,contentType:typeof value==='string'?'markdown':'json',editable:!readOnly,editorProps:{attributes:{'aria-label':label,role:'textbox','aria-multiline':'true'},handleDOMEvents:{
    paste:(_view,event)=>paste.current(event),
    click(view,event){
      if(!view.editable||!(event.target instanceof HTMLImageElement)||event.shiftKey||event.metaKey||event.ctrlKey)return false;
      const position=view.posAtDOM(event.target,0);
      if(view.state.doc.nodeAt(position)?.type.name!=='image')return false;
      event.preventDefault();
      view.focus();
      const {state}=view;
      view.dispatch(state.tr.setSelection(NodeSelection.create(state.doc,position)).setMeta('pointer',true));
      return true;
    },
  }},onCreate:({editor})=>{callbacks.current.onChange?.(editorContent(editor));outline(editor);},onUpdate:({editor})=>{callbacks.current.onChange?.(editorContent(editor));outline(editor);},onSelectionUpdate:({editor})=>{const {from,to}=editor.state.selection;callbacks.current.onSelection?.(editor.state.doc.textBetween(from,to,'\n'));const start=editor.state.doc.resolve(from);const end=editor.state.doc.resolve(to);callbacks.current.onSelectionRange?.(from===to?null:{from:start.index(0),to:Math.min(editor.state.doc.childCount,end.index(0)+(end.depth>0&&to>end.start(1)?1:0))});}});
 function outline(instance:NonNullable<typeof editor>){const entries:HeadingEntry[]=[];const seen=new Set<string>();const parents:Record<number,string>={};instance.state.doc.descendants((node,pos)=>{if(node.type.name!=='heading')return;const text=node.textContent;const number=text.match(/^(\d+(?:\.\d+)*)(?:[.、．])?\s*(?=[^\d.])/);const level=number?Math.min(3,number[1].split('.').length):Number(node.attrs.level);const normalized=text.replace(/\s+/g,'');const key=number||level===1?normalized:[...Array.from({length:level-1},(_,i)=>parents[i+1]||''),normalized].join('|');if(seen.has(key))return;seen.add(key);parents[level]=normalized;for(const n of Object.keys(parents))if(Number(n)>level)delete parents[Number(n)];entries.push({text,level,position:pos,blockFrom:instance.state.doc.resolve(pos).index(0)});});callbacks.current.onOutline?.(entries);}
 useEffect(()=>{if(!editor)return;const current=editorContent(editor);if(typeof value==='string'){if(editor.getMarkdown()!==value){editor.commands.setContent(value,{contentType:'markdown',emitUpdate:false});outline(editor);}}else if(JSON.stringify(current)!==JSON.stringify(value)){editor.commands.setContent(value,{emitUpdate:false});outline(editor);}},[value,editor]);
 useEffect(()=>{if(!editor)return;editor.setEditable(!readOnly);},[readOnly,editor]);
 useEffect(()=>{const root=frame.current;const toolbar=root?.querySelector<HTMLElement>('.rich-toolbar');if(!toolbar)return;const measure=()=>root!.style.setProperty('--rich-toolbar-height',toolbar.offsetHeight+'px');measure();const observer=new ResizeObserver(measure);observer.observe(toolbar);return()=>observer.disconnect();},[editor,readOnly]);
 useEffect(()=>{function jump(event:Event){const {position}=((event as CustomEvent).detail||{});if(editor&&typeof position==='number'&&label==='文档正文'){editor.commands.focus();editor.commands.setTextSelection(position+1);editor.view.domAtPos(position+1).node.parentElement?.scrollIntoView({block:'center',behavior:'smooth'});}}window.addEventListener('document-heading',jump);return()=>window.removeEventListener('document-heading',jump);},[editor,label]);
 if(!editor)return <p className="muted">正在加载富文本编辑器…</p>;
 async function insertImages(files:File[], markup?:HTMLTemplateElement, replaceSelection=true){
  if(!editor?.isEditable||!uploadImage)return;
  if(uploadingRef.current){setImageError('正在上传图片，请稍后再次粘贴。');return;}
  const upload=uploadImage;
  const selection=editor.state.selection;
  let bookmark=(replaceSelection?selection:Selection.near(editor.state.doc.resolve(selection.to))).getBookmark();
  if(!replaceSelection)editor.view.focus();
  const track=({transaction}:{transaction:Transaction})=>{bookmark=bookmark.map(transaction.mapping);};
  editor.on('transaction',track);
  uploadingRef.current=true;setUploading(true);onImageUploadChange?.(true);setImageError('');
  try{
    const images=markup ? Array.from(markup.content.querySelectorAll('img')) : [];
    const nodes=[];
    let failure='';
    let inserted=0;
    for(let i=0;i<(markup?images.length:files.length);i++){
      const image=images[i];
      try {
        const file=image ? await imageFromClipboardElement(image, files[i]) : files[i];
        validateClipboardImage(file);
        const attrs=await upload(file);
        if(image){image.setAttribute('src',attrs.src);image.setAttribute('alt',attrs.alt);}
        else nodes.push(editor.schema.nodes.image.create(attrs));
        inserted++;
      } catch(reason){
        image?.remove();
        failure ||= reason instanceof Error?reason.message:'上传图片失败';
      }
      if(editor.isDestroyed||!editor.isEditable)return;
    }
    const content=markup ? DOMParser.fromSchema(editor.schema).parse(markup.content).content : Fragment.fromArray(nodes);
    if(inserted||markup&&(markup.content.textContent?.trim()||markup.content.querySelector('table'))){
      const state=editor.state;
      const target=bookmark.resolve(state.doc);
      const transaction=state.tr.setSelection(target).replaceSelection(new Slice(content,0,0));
      if(state.selection.eq(target))transaction.scrollIntoView();
      else transaction.setSelection(state.selection.map(transaction.doc,transaction.mapping));
      if(transaction.docChanged)editor.view.dispatch(transaction);
      else if(!failure)failure='请选择可插入图片的位置后重试。';
    }
    setImageError(failure);
  }catch(reason){setImageError(reason instanceof Error?reason.message:'上传图片失败');}
  finally {
    editor.off('transaction',track);
    uploadingRef.current=false;setUploading(false);onImageUploadChange?.(false);
  }
 }
 paste.current=event=>{
  const clipboard=event.clipboardData;
  if(!editor.isEditable||!uploadImage||!clipboard)return false;
  const html=clipboard.getData('text/html');
  const files=clipboardImages(clipboard);
  try{
    const markup=/<(?:img|table)(?:\s|\/?>)/i.test(html)?clipboardMarkup(html):undefined;
    const merged=markup&&normalizeClipboardTables(markup.content);
    if(markup?.content.querySelector('img')||files.length&&!markup?.content.querySelector('table')){
      event.preventDefault();
      void insertImages(files,markup?.content.querySelector('img')?markup:undefined);
      return true;
    }
    const table=!html?clipboardTextTable(clipboard.getData('text/plain')):null;
    if(merged||table){
      event.preventDefault();
      setImageError('');
      editor.view.pasteHTML(table?.outerHTML??markup!.innerHTML,event);
      return true;
    }
  }catch(reason){
    event.preventDefault();
    setImageError(reason instanceof Error?reason.message:'粘贴失败，请重试。');
    return true;
  }
  return false;
 };
 const button=(text:string,action:()=>void,active=false)=><button type="button" className={'rich-tool '+(active?'active':'')} onMouseDown={e=>e.preventDefault()} onClick={action}>{text}</button>;
 return <div className="rich-editor" ref={frame}>{!readOnly&&<div className="rich-toolbar" role="toolbar" aria-label={label+'格式工具'}><select aria-label={label+'标题级别'} value={editor.isActive('heading',{level:1})?'1':editor.isActive('heading',{level:2})?'2':editor.isActive('heading',{level:3})?'3':'0'} onChange={e=>{const n=Number(e.target.value);if(n)editor.chain().focus().setHeading({level:n as 1|2|3}).run();else editor.chain().focus().setParagraph().run();}}><option value="0">正文</option><option value="1">一级标题</option><option value="2">二级标题</option><option value="3">三级标题</option></select>{button('加粗',()=>{editor.chain().focus().toggleBold().run();},editor.isActive('bold'))}{button('斜体',()=>{editor.chain().focus().toggleItalic().run();},editor.isActive('italic'))}{button('项目列表',()=>{editor.chain().focus().toggleBulletList().run();},editor.isActive('bulletList'))}{button('编号列表',()=>{editor.chain().focus().toggleOrderedList().run();},editor.isActive('orderedList'))}{button('插入表格',()=>{editor.chain().focus().insertTable({rows:3,cols:2,withHeaderRow:true}).run();})}{editor.isActive('table')&&<>{button('添加行',()=>{editor.chain().focus().addRowAfter().run();})}{button('添加列',()=>{editor.chain().focus().addColumnAfter().run();})}{button('删除行',()=>{editor.chain().focus().deleteRow().run();})}{button('删除表格',()=>{editor.chain().focus().deleteTable().run();})}</>} {uploadImage&&<><button type="button" className="rich-tool" disabled={uploading} onMouseDown={e=>e.preventDefault()} onClick={()=>imageInput.current?.click()}>{uploading?'上传图片中…':'插入图片'}</button><input ref={imageInput} type="file" accept="image/png,image/jpeg" aria-label="选择图片" hidden onChange={event=>{const file=event.currentTarget.files?.[0];event.currentTarget.value='';if(file)void insertImages([file],undefined,false);}}/></>}{onComment&&button('批注',onComment)}
   {alignments.map(({value,label})=>{
    const active=editor.isActive({textAlign:value})||(value==='left'&&editor.isActive({textAlign:null}));
    return <button type="button" key={value} className={'rich-tool '+(active?'active':'')}
      aria-pressed={active} onMouseDown={event=>event.preventDefault()} onClick={()=>{
       const {state,view}=editor;
       const selection=state.selection;
       if(selection instanceof NodeSelection&&selection.node.type.name==='image'){
        view.dispatch(state.tr.setNodeAttribute(selection.from,'textAlign',value));
        view.focus();
       }else{
        const attrs={textAlign:value};
        editor.chain().focus().updateAttributes('paragraph',attrs).updateAttributes('heading',attrs).run();
       }
      }}>{label}</button>;
   })}</div>}{imageError&&<p className="form-error" role="alert">{imageError}</p>}{sidePanel?<div className={showSidePanel?'workspace-manuscript-columns':undefined}><EditorContent editor={editor}/>{sidePanel}</div>:<EditorContent editor={editor}/>}</div>;
}
