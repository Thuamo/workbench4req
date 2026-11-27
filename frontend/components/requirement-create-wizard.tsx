'use client';

import {useRef, useState, type FormEvent} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {Upload} from 'lucide-react';
import {api} from '../lib/api';
import type {Base, Requirement, Version} from '../lib/types';
import {DocumentChoices, useSelectableDocuments} from './document-choices';
import {Modal} from './ui';

type Source = Pick<Version, 'id' | 'document_id' | 'filename' | 'parse_status'>;
const documentTypes = '.docx,.doc,.pdf,.xlsx,.xls,.pptx,.txt,.md,.csv';

export function RequirementCreateWizard({close, done}: {
  close: () => void;
  done: (requirement: Requirement) => void;
}) {
  const query = useQueryClient();
  const busyRef = useRef(false);
  const [step, setStep] = useState<'details' | 'confirm'>('details');
  const [number, setNumber] = useState('');
  const [title, setTitle] = useState('');
  const [system, setSystem] = useState('');
  const [initializeTasks, setInitializeTasks] = useState(true);
  const [createClarification, setCreateClarification] = useState(true);
  const [uploaded, setUploaded] = useState<Source | null>(null);
  const [existingId, setExistingId] = useState('');
  const [busy, setBusy] = useState<'upload' | 'retry' | 'save' | null>(null);
  const [error, setError] = useState('');

  const {data: bases = [], isPending: loadingBases} = useQuery({
    queryKey: ['bases'],
    queryFn: () => api<Base[]>('/knowledge-bases'),
  });
  const base = bases.find(item => item.enabled);
  const {data: documents = []} = useSelectableDocuments();
  const eligibleDocuments = documents.filter(doc => ['business', 'reference'].includes(doc.kind));
  const existing = eligibleDocuments.flatMap(doc => doc.versions).find(version => version.id === existingId);
  const {data: currentUpload, error: statusError} = useQuery({
    queryKey: ['requirement-upload', uploaded?.id],
    enabled: !!uploaded,
    queryFn: async () => {
      const versions = await api<Source[]>('/documents/' + uploaded!.document_id + '/versions');
      const version = versions.find(item => item.id === uploaded!.id);
      if (!version) throw new Error('上传的文档版本已不可用，请重新选择。');
      return version;
    },
    refetchInterval: result => ['ready', 'failed'].includes(result.state.data?.parse_status ?? '') ? false : 1500,
  });
  const source = currentUpload ?? uploaded ?? existing;

  async function upload(file: File) {
    if (!base || busyRef.current) return;
    busyRef.current = true;
    setBusy('upload');
    setError('');
    try {
      const data = new FormData();
      data.append('file', file);
      data.append('title', (file.name.replace(/\.[^.]+$/, '') || file.name).slice(0, 300));
      data.append('base_id', base.id);
      data.append('kind', 'business');
      setUploaded(await api<Source>('/documents/upload', 'POST', data));
      setExistingId('');
      void query.invalidateQueries({queryKey: ['documents-all']});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档上传失败');
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  async function retryParse() {
    if (!uploaded || busyRef.current) return;
    busyRef.current = true;
    setBusy('retry');
    setError('');
    try {
      await api('/versions/' + uploaded.id + '/retry-parse', 'POST');
      await query.invalidateQueries({queryKey: ['requirement-upload', uploaded.id]});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重新解析失败');
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current) return;
    setError('');
    if (!number.trim() || !title.trim() || (initializeTasks && !system.trim())) {
      setError(initializeTasks ? '请填写需求编号、需求名称和系统。' : '请填写需求编号和需求名称。');
      return;
    }
    if (initializeTasks && !source) {
      setError('请先上传文档或选择已有文档。');
      return;
    }
    if (source && source.parse_status !== 'ready') {
      setError('请等待文档解析完成，或重新选择文件。');
      return;
    }
    if (step === 'details') {
      setStep('confirm');
      return;
    }

    busyRef.current = true;
    setBusy('save');
    try {
      const result = await api<Requirement>('/requirements/create-from-wizard', 'POST', {
        requirement: {
          number: number.trim(), title: title.trim(),
          tags: system.trim() ? {系统: [system.trim()]} : {},
          source_version_id: source?.id ?? null,
        },
        initialize_tasks: initializeTasks,
        create_clarification: createClarification,
      });
      void query.invalidateQueries();
      close();
      done(result);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '创建需求失败';
      setError(message);
      if (message.includes('需求已存在')) setStep('details');
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  return <Modal title="新增业务需求" close={() => {if (!busyRef.current) close();}}>
    <form onSubmit={submit}>
      <div className="form-fields">
        {step === 'details' ? <>
          <label className="drop-zone">
            <Upload size={20}/>
            <strong>上传文档</strong>
            <small>选择本地需求文档，上传后自动解析</small>
            <input aria-label="上传文档" type="file" accept={documentTypes} disabled={!!busy || !base}
              onChange={event => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = '';
                if (file) void upload(file);
              }}/>
          </label>
          {busy === 'upload' && <p role="status">正在上传文档…</p>}
          {!base && <p className="muted">{loadingBases ? '正在读取知识库…' : '没有可用的知识库，暂时无法上传本地文档。'}</p>}
          {source && <div className="toolbar">
            <span role="status">{source.filename} · {source.parse_status === 'ready' ? '解析完成'
              : source.parse_status === 'failed' ? '解析失败' : '正在解析'}</span>
            {uploaded && source.parse_status === 'failed' && <button type="button" className="text-button"
              disabled={!!busy} onClick={() => void retryParse()}>重试解析</button>}
            <button type="button" className="text-button" disabled={!!busy}
              onClick={() => {setUploaded(null); setExistingId(''); setError('');}}>移除选择</button>
          </div>}
          {statusError && <p className="form-error" role="alert">{statusError.message}</p>}
          <details>
            <summary>从知识库选择已有文档</summary>
            <DocumentChoices documents={eligibleDocuments} value={existingId ? [existingId] : []} single
              onChange={ids => {if (!busyRef.current) {setUploaded(null); setExistingId(ids[0] ?? ''); setError('');}}}/>
          </details>
          <label>需求编号<input required maxLength={80} value={number} onChange={e => setNumber(e.target.value)}/></label>
          <label>需求名称<input required maxLength={300} value={title} onChange={e => setTitle(e.target.value)}/></label>
          <label>系统<input required={initializeTasks} maxLength={200} value={system} onChange={e => setSystem(e.target.value)}/></label>
          <label className="checkbox-label"><input type="checkbox" checked={initializeTasks}
            onChange={e => setInitializeTasks(e.target.checked)}/>是否初始化基础任务</label>
          <label className="checkbox-label"><input type="checkbox" checked={createClarification}
            onChange={e => setCreateClarification(e.target.checked)}/>是否生成澄清计划</label>
        </> : <>
          <p><strong>{number.trim()} · {title.trim()}</strong></p>
          {system.trim() && <p>系统：{system.trim()}</p>}
          {source && <p>需求文档：{source.filename}</p>}
          <p>{initializeTasks ? '初始化四项基础任务' : '不初始化基础任务'}</p>
          <p>{createClarification ? '生成澄清计划' : '不生成澄清计划'}</p>
        </>}
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>
      <footer>
        <button type="button" className="secondary" disabled={!!busy}
          onClick={() => {if (step === 'confirm') {setStep('details'); setError('');} else close();}}>
          {step === 'confirm' ? '上一步' : '取消'}
        </button>
        <button type="submit" className="primary" disabled={!!busy}>
          {busy === 'save' ? '正在创建…' : step === 'confirm' ? '确认创建' : '下一步'}
        </button>
      </footer>
    </form>
  </Modal>;
}
