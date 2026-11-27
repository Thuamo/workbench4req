'use client';
import {createContext,useContext,useRef,useState,ReactNode} from 'react';
import {Modal} from './ui';
type Guard={dirty:()=>boolean;save:()=>Promise<boolean>;discard:()=>void};
const Context=createContext<{setGuard:(guard:Guard|null)=>void;request:(action:()=>void)=>void;isDirty:()=>boolean}>({setGuard:()=>{},request:action=>action(),isDirty:()=>false});
export const useNavigationGuard=()=>useContext(Context);
export function NavigationGuard({children}:{children:ReactNode}) {
  const guard=useRef<Guard|null>(null);const [pending,setPending]=useState<(()=>void)|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  function leave(){const action=pending;setPending(null);guard.current=null;action?.();}
  return <Context.Provider value={{isDirty:()=>Boolean(guard.current?.dirty()),setGuard:value=>{guard.current=value;},request:action=>{if(guard.current?.dirty()){setError('');setPending(()=>action);}else action();}}}>{children}{pending&&<Modal title="保存编辑后离开？" close={()=>{if(!busy)setPending(null);}}><div className="form-fields"><p>当前文档有尚未保存的修改。保存后可以从首页“继续处理”返回编辑。</p>{error&&<p className="form-error">{error}</p>}</div><footer><button disabled={busy} className="secondary" onClick={()=>setPending(null)}>继续编辑</button><button disabled={busy} className="secondary" onClick={()=>{guard.current?.discard();leave();}}>放弃未保存修改</button><button disabled={busy} className="primary" onClick={async()=>{setBusy(true);try{if(await guard.current?.save())leave();else setError('保存未成功，请重试或继续编辑。');}finally{setBusy(false);}}}>保存并离开</button></footer></Modal>}</Context.Provider>;
}
