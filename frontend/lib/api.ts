import { readJsonResponse } from './http';

export async function csrfHeaders(): Promise<Record<string,string>> {
  let token = document.cookie.split('; ').find(c => c.startsWith('csrf='))?.slice(5);
  if (!token) {
    const response=await fetch('/api/auth/csrf',{credentials:'include'});
    const body=await readJsonResponse<{csrf_token?:unknown}>(response);
    if (typeof body?.csrf_token!=='string'||!body.csrf_token) throw new Error('无法获取安全令牌，请刷新页面后重试。');
    token=body.csrf_token;
  }
  return {'X-CSRF-Token':decodeURIComponent(token || '')};
}
export async function api<T>(path:string, method='GET', data?:unknown):Promise<T> {
  const headers: Record<string,string> = method==='GET' ? {} : await csrfHeaders();
  if (data!==undefined && !(data instanceof FormData)) headers['Content-Type']='application/json';
  const response=await fetch('/api'+path,{method,headers,credentials:'include',body:data===undefined?undefined:data instanceof FormData?data:JSON.stringify(data)});
  return readJsonResponse<T>(response);
}
export const date=(value:string)=>new Date(value.endsWith('Z')?value:value+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
export const states:Record<string,string>={draft:'草稿',pending_review:'待审核',in_review:'审核中',approved:'已通过',published:'已发布',superseded:'历史版本',deprecated:'已废止',archived:'已归档',pending:'待处理',completed:'已完成',returned:'已退回',cancelled:'已取消',ready:'可用',failed:'失败',running:'执行中',awaiting_confirmation:'等待人工确认',confirmed:'已确认',candidate:'待确认',rejected:'已拒绝',open:'未处理',answered:'已反馈',not_needed:'无需澄清',in_progress:'进行中',not_submitted:'未提交',not_published:'未发布',queued:'已排队',not_built:'未构建',building:'构建中',clarifying:'澄清中',specified:'已编制'};
