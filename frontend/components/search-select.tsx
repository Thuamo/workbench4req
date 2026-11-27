'use client';
import {Children,isValidElement,useEffect,useId,useRef,useState,ReactNode,SelectHTMLAttributes,ChangeEvent} from 'react';
import {createPortal} from 'react-dom';
import {ChevronDown,Search,Check} from 'lucide-react';

function labelText(value:ReactNode):string {
  if(value==null||typeof value==='boolean')return '';
  if(typeof value==='string'||typeof value==='number')return String(value);
  if(isValidElement<{children?:ReactNode}>(value))return labelText(value.props.children);
  return Children.toArray(value).map(labelText).join('');
}

export function SearchSelect({children,value,defaultValue,onChange,disabled,required,className,style,name,id,...rest}:SelectHTMLAttributes<HTMLSelectElement>) {
  const options=Children.toArray(children).flatMap(child=>isValidElement<{value?:string|number;children?:ReactNode;disabled?:boolean}>(child)?[{value:String(child.props.value??labelText(child.props.children)),label:labelText(child.props.children),disabled:!!child.props.disabled}]:[]);
  const [local,setLocal]=useState(String(defaultValue??options[0]?.value??''));
  const selected=String(value??local);
  const choice=options.find(option=>option.value===selected);
  const [open,setOpen]=useState(false);
  const [query,setQuery]=useState('');
  const [active,setActive]=useState(0);
  const [position,setPosition]=useState({left:0,top:0,width:230,maxHeight:300});
  const root=useRef<HTMLDivElement>(null);
  const menu=useRef<HTMLDivElement>(null);
  const generated=useId();
  const listId=generated+'-options';
  const filtered=options.filter(option=>!option.value||(option.label+' '+option.value).normalize('NFKC').toLowerCase().includes(query.normalize('NFKC').toLowerCase()));
  useEffect(()=>{
    if(!open)return;
    function place(){const rect=root.current?.getBoundingClientRect();if(!rect)return;const height=Math.min(320,window.innerHeight-20);const below=window.innerHeight-rect.bottom-10;const above=below<200&&rect.top>below;setPosition({left:Math.max(8,Math.min(rect.left,window.innerWidth-Math.max(rect.width,230)-8)),top:above?Math.max(8,rect.top-height-4):rect.bottom+4,width:Math.min(Math.max(rect.width,230),window.innerWidth-16),maxHeight:above?Math.min(height,rect.top-12):Math.max(120,Math.min(height,below))});}
    function outside(event:PointerEvent){if(!root.current?.contains(event.target as Node)&&!menu.current?.contains(event.target as Node))setOpen(false);}
    place();document.addEventListener('pointerdown',outside);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
    return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
  },[open]);
  function choose(next:string){const target={value:next,name:name||''} as HTMLSelectElement;onChange?.({target,currentTarget:target} as ChangeEvent<HTMLSelectElement>);setLocal(target.value);setOpen(false);setQuery('');root.current?.querySelector('button')?.focus();}
  return <div ref={root} className={'search-select '+(className||'')} style={style}>
    <button type="button" id={id} name={name} role="combobox" aria-label={rest['aria-label']} aria-labelledby={rest['aria-labelledby']} aria-expanded={open} aria-controls={listId} aria-haspopup="listbox" aria-required={required} disabled={disabled} title={rest.title} className="search-select-trigger" onClick={()=>{setOpen(!open);setQuery('');setActive(0);}} onKeyDown={event=>{if(event.key==='ArrowDown'||event.key==='Enter'){event.preventDefault();setOpen(true);setQuery('');setActive(0);}if(event.key==='Escape')setOpen(false);}}><span>{choice?.label||selected||'请选择'}</span><ChevronDown size={14}/></button>
    {open&&typeof document!=='undefined'&&createPortal(<div ref={menu} className="search-select-menu" style={{position:'fixed',left:position.left,top:position.top,width:position.width,maxHeight:position.maxHeight}}><div className="search-select-filter"><Search size={15}/><input autoFocus aria-label="搜索选项" placeholder="输入关键词搜索匹配…" value={query} onChange={event=>{setQuery(event.target.value);setActive(0);}} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();setOpen(false);}if(event.key==='Tab')setOpen(false);if(event.key==='ArrowDown'){event.preventDefault();setActive(Math.min(active+1,filtered.length-1));}if(event.key==='ArrowUp'){event.preventDefault();setActive(Math.max(0,active-1));}if(event.key==='Enter'){event.preventDefault();const option=filtered[active];if(option&&!option.disabled)choose(option.value);}}}/></div><div id={listId} role="listbox" className="search-select-options">{filtered.map((option,index)=><button type="button" role="option" aria-selected={option.value===selected} disabled={option.disabled} className={index===active?'highlight':''} key={option.value} onPointerMove={()=>setActive(index)} onClick={()=>choose(option.value)}><span>{option.label}</span>{option.value===selected&&<Check size={14}/>}</button>)}{!filtered.length&&<p>没有匹配选项</p>}</div></div>,document.body)}
  </div>;
}
