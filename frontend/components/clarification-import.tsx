'use client';

import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {History, Upload} from 'lucide-react';
import {api, date} from '../lib/api';
import {Empty, Loading, Modal, Tabs, useAction} from './ui';

const labels = {add:'新增', update:'更新', unchanged:'无变化', conflict:'冲突'};
type PreviewRow = {
  sheet:string; row:number; number:string; name:string; action:keyof typeof labels;
  reason:string; changed_fields:string[]; associate_requirement:boolean;
};
type ImportCounts = {added:number; updated:number; unchanged:number; conflicts:number};
type ImportPreview = ImportCounts & {incoming_count:number; snapshot:string; rows:PreviewRow[]};
type ImportBatch = {id:string; filename:string; created_at:string; added:number; updated:number; undone:boolean};

function PreviewTable({preview}:{preview:ImportPreview}) {
  const [filter,setFilter] = useState('all');
  const [page,setPage] = useState(0);
  const tabs = [
    {key:'all',label:`全部 ${preview.incoming_count}`}, {key:'add',label:`新增 ${preview.added}`},
    {key:'update',label:`更新 ${preview.updated}`}, {key:'conflict',label:`冲突 ${preview.conflicts}`},
    {key:'unchanged',label:`无变化 ${preview.unchanged}`},
  ];
  const rows = filter==='all' ? preview.rows : preview.rows.filter(row=>row.action===filter);
  const pageSize = 10;
  return <>
    <Tabs items={tabs} value={filter} onChange={key=>{setFilter(key);setPage(0);}}/>
    {rows.length ? <div className="table-wrap"><table className="ledger-import-table">
      <thead><tr><th>Excel 位置</th><th>需求编号与名称</th><th>处理结果</th><th>变更或冲突说明</th></tr></thead>
      <tbody>{rows.slice(page*pageSize,(page+1)*pageSize).map(row=><tr key={`${row.sheet}:${row.row}`}>
        <td>{row.sheet} · 第 {row.row} 行</td><td>{row.number||'—'}{row.name&&<small className="block muted">{row.name}</small>}</td>
        <td>{labels[row.action]}</td><td>{row.reason||[...row.changed_fields,...(row.associate_requirement?['关联需求']:[])].join('、')||'—'}</td>
      </tr>)}</tbody>
    </table></div> : <p className="muted small">当前分类没有记录。</p>}
    {rows.length>pageSize&&<div className="pagination">
      <span>第 {page+1} 页，共 {Math.ceil(rows.length/pageSize)} 页</span>
      <button className="secondary" disabled={page===0} onClick={()=>setPage(page-1)}>上一页</button>
      <button className="secondary" disabled={(page+1)*pageSize>=rows.length} onClick={()=>setPage(page+1)}>下一页</button>
    </div>}
  </>;
}

export function ClarificationImport({onImported}:{onImported:()=>void}) {
  const {perform} = useAction();
  const [file,setFile] = useState<File|null>(null);
  const [preview,setPreview] = useState<ImportPreview|null>(null);
  const [previewError,setPreviewError] = useState('');
  const [previewBusy,setPreviewBusy] = useState(false);
  const [showHistory,setShowHistory] = useState(false);
  const [undoBatch,setUndoBatch] = useState<ImportBatch|null>(null);
  const [undoBusy,setUndoBusy] = useState(false);
  const history = useQuery({queryKey:['ledger-imports'],queryFn:()=>api<ImportBatch[]>('/clarification/imports'),enabled:showHistory});

  async function previewFile(next:File) {
    setFile(next);setPreview(null);setPreviewError('');setPreviewBusy(true);
    const data = new FormData();
    data.append('file',next);
    try {
      setPreview(await api<ImportPreview>('/clarification/import-preview','POST',data));
    } catch(error) {
      setPreviewError(error instanceof Error ? error.message : '文件校验失败，请重新选择 Excel。');
    } finally {
      setPreviewBusy(false);
    }
  }

  async function confirmImport() {
    if(!file||!preview||previewBusy) return;
    setPreviewBusy(true);
    const data = new FormData();
    data.append('file',file);
    data.append('expected_snapshot',preview.snapshot);
    const result = await perform(async()=>{
      try {
        return await api<ImportCounts>('/clarification/import','POST',data);
      } catch(error) {
        setPreviewError(error instanceof Error ? error.message : '导入失败，请重新预览。');
        throw error;
      }
    },`导入完成，新增 ${preview.added} 条，更新 ${preview.updated} 条，跳过冲突 ${preview.conflicts} 条`);
    setPreviewBusy(false);
    if(result){setFile(null);setPreview(null);onImported();}
  }

  async function confirmUndo() {
    if(!undoBatch||undoBusy) return;
    setUndoBusy(true);
    const result = await perform(()=>api(`/clarification/imports/${undoBatch.id}/undo`,'POST'),'已撤销导入批次');
    setUndoBusy(false);
    if(result) setUndoBatch(null);
  }

  return <>
    <label className="secondary upload-button"><Upload size={15}/>Excel 导入<input type="file" accept=".xlsx" hidden disabled={!!file} onChange={event=>{
      const next=event.target.files?.[0];
      if(next) void previewFile(next);
      event.target.value='';
    }}/></label>
    <button className="secondary" onClick={()=>setShowHistory(true)}><History size={15}/>导入记录</button>
    {file&&<Modal title="预览 Excel 增量导入" wide close={()=>{if(!previewBusy) setFile(null);}}>
      <div className="form-fields">
        <p>{file.name}</p>
        {previewBusy&&!preview&&<Loading/>}
        {preview&&<>
          <p className="notice">按需求编号匹配本人登记的计划。空单元格保留原值，冲突行跳过，请人工核对后再导入。</p>
          <PreviewTable preview={preview}/>
        </>}
        {previewError&&<p className="form-error" role="alert">{previewError}</p>}
      </div>
      <footer>
        <button className="secondary" disabled={previewBusy} onClick={()=>setFile(null)}>关闭</button>
        {previewError&&<button className="secondary" disabled={previewBusy} onClick={()=>void previewFile(file)}>重新预览</button>}
        <button className="primary" disabled={previewBusy||!preview||!!previewError||preview.added+preview.updated===0} onClick={()=>void confirmImport()}>
          {previewBusy&&preview?'正在导入…':'确认导入'}
        </button>
      </footer>
    </Modal>}
    {showHistory&&<Modal title={undoBatch?'撤销导入批次':'导入记录'} close={()=>{
      if(undoBusy) return;
      if(undoBatch) setUndoBatch(null);else setShowHistory(false);
    }}>
      {undoBatch ? <>
        <div className="form-fields"><p><strong>{undoBatch.filename}</strong> · {date(undoBatch.created_at)}</p>
          <p>恢复导入前的台账字段，并从台账移除本次新增计划。历史记录和业务需求会保留。</p>
        </div>
        <footer>
          <button className="secondary" disabled={undoBusy} onClick={()=>setUndoBatch(null)}>取消</button>
          <button className="primary" disabled={undoBusy} onClick={()=>void confirmUndo()}>{undoBusy?'正在撤销…':'确认撤销'}</button>
        </footer>
      </> : <div className="form-fields">
        {history.isLoading ? <Loading/> : history.isError ? <p className="form-error" role="alert">{history.error.message}</p> : history.data?.length ?
          <div className="table-wrap"><table className="ledger-import-table">
            <thead><tr><th>文件与时间</th><th>导入结果</th><th>操作</th></tr></thead>
            <tbody>{history.data.map(batch=><tr key={batch.id}>
              <td>{batch.filename}<small className="block muted">{date(batch.created_at)}</small></td>
              <td>新增 {batch.added} 条 · 更新 {batch.updated} 条</td>
              <td>{batch.undone?'已撤销':<button className="text-button" onClick={()=>setUndoBatch(batch)}>撤销批次</button>}</td>
            </tr>)}</tbody>
          </table></div> : <Empty text="暂无增量导入记录" detail="完成增量导入的批次会显示在这里。"/>}
      </div>}
    </Modal>}
  </>;
}
