'use client';

import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../lib/api';
import {Loading,Modal,useAction} from './ui';

type Asset = {document_id:string;version_id:string;title:string;label:string};
type Setup = {sources:{name:string;ready_count:number;restricted:boolean}[];targets:Asset[];issues:string[];max_source_files:number};
type Result = {drafts:Asset[];reused:boolean};

export function KnowledgeConsolidation({baseId,close,openVersion}: {
  baseId:string;close:()=>void;openVersion:(asset:Asset)=>void;
}) {
  const endpoint='/knowledge-bases/'+baseId+'/consolidation';
  const {data,isLoading,error}=useQuery({queryKey:['knowledge-consolidation',baseId],queryFn:()=>api<Setup>(endpoint)});
  const {perform}=useAction();
  const [busy,setBusy]=useState(false);
  const [result,setResult]=useState<Result|null>(null);

  async function generate() {
    setBusy(true);
    try {
      const created=await perform(()=>api<Result>(endpoint,'POST'));
      if(created) setResult(created);
    } finally {setBusy(false);}
  }

  return <Modal title="知识沉淀" close={close}>
    <div className="form-fields">
      {isLoading&&<Loading/>}
      {error&&<p className="form-error">{error.message}</p>}
      {data&&<>
        <section>
          <h3>来源资料</h3>
          <ul>{data.sources.map(source=><li key={source.name}>{source.name} · {source.ready_count} 份可用正式文件
            {source.restricted&&'（部分资料的授权范围小于目标库）'}</li>)}</ul>
          <p className="muted">系统将可用资料的正文片段与目标文件对照，单次最多处理 {data.max_source_files} 份。资料较长时分段抽样。</p>
        </section>
        <section>
          <h3>目标文件</h3>
          <ul>{data.targets.map(target=><li key={target.document_id}>{target.title} · {target.label}</li>)}</ul>
          <p className="muted">能力地图新增沉淀工作表，白皮书新增更新章节。每条建议附来源与定位，草稿可提交审核。</p>
        </section>
        {data.issues.map(issue=><p className="notice" key={issue}>{issue}</p>)}
        {result?<section aria-live="polite">
          <h3>{result.drafts.length?(result.reused?'已有更新草稿':'更新草稿已生成'):'本次没有找到有充分依据的更新建议'}</h3>
          {result.drafts.map(draft=><div key={draft.version_id}>
            <button type="button" className="text-button" onClick={()=>openVersion(draft)}>{draft.title} · {draft.label}</button>
          </div>)}
        </section>:<div className="button-group">
          <button type="button" className="primary" disabled={busy||!!data.issues.length} onClick={()=>void generate()}>
            {busy?'正在分析资料…':'生成更新草稿'}
          </button>
          {busy&&<span className="muted" role="status">正在比较来源与现有文件，请等待分析完成。</span>}
        </div>}
      </>}
    </div>
  </Modal>;
}
