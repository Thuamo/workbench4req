import type {Version,Run} from './types';
export type Destination={page:string;id:string;document_id?:string};
export type WorkItem={id:string;title:string;stage:string;label:string;action:string;created_at:string;destination:Destination;requirement_id?:string};
export function versionStage(v:Version){
 if(v.parse_status==='failed')return '资料解析失败';
 if(v.parse_status!=='ready')return '资料解析中';
 if(v.status==='published')return '已正式发布';
 if(v.review_status==='returned')return '审核退回 · 请创建修订';
 if(['pending_review','in_review'].includes(v.status))return '会签审核中';
 if(v.review_status==='approved')return v.index_status==='failed'||v.publish_status==='failed'?'发布失败 · 可重试':'会签通过 · 发布处理中';
 if(['superseded','deprecated','archived'].includes(v.status))return '历史版本';
 return '版本已确认 · 未提交审核';
}
export function runStage(r:Run){if(r.status==='awaiting_confirmation')return '等待确认提纲';if(r.status==='failed')return '生成失败 · 可重试';if(['pending','running'].includes(r.status))return '正在生成';if(r.result.editor_draft)return '编辑中 · 已保存进度';return r.result.saved_version_id?'版本已确认':'正文已生成 · 待编辑确认';}
