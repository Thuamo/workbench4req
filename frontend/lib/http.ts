function statusMessage(status: number): string {
  if (status===502||status===503||status===504) return `后端服务暂时不可用（HTTP ${status}），请确认 API 已启动，稍后重试。`;
  if (status>=500) return `服务处理失败（HTTP ${status}），请稍后重试或查看服务日志。`;
  return `请求失败（HTTP ${status}），请刷新页面后重试。`;
}

function detailMessage(body: unknown): string | undefined {
  if (!body||typeof body!=='object'||!('detail' in body)) return;
  const detail=(body as {detail:unknown}).detail;
  if (typeof detail==='string'&&detail.trim()) return detail;
  if (detail&&typeof detail==='object'&&!Array.isArray(detail)&&'message' in detail) {
    const value=detail as {message:unknown;reason?:unknown;version_id?:unknown;filename?:unknown};
    return [value.message,value.reason,(value.filename||value.version_id)&&`文件：${value.filename||value.version_id}`].filter(v=>typeof v==='string').join('；');
  }
  if (Array.isArray(detail)) {
    const messages=detail.flatMap(item=>item&&typeof item==='object'&&typeof item.msg==='string'?[item.msg]:[]);
    if (messages.length) return messages.join('；');
  }
}

export async function readJsonResponse<T=unknown>(response: Response): Promise<T> {
  const text=await response.text();
  if (response.ok&&(response.status===204||response.status===205)) return undefined as T;
  let body: unknown;
  try {
    body=JSON.parse(text) as unknown;
  } catch {
    if (!response.ok) throw new Error(statusMessage(response.status));
    throw new Error('接口返回了非 JSON 数据，请确认后端 API 和前端代理配置。');
  }
  if (!response.ok) throw new Error(detailMessage(body)||statusMessage(response.status));
  return body as T;
}
