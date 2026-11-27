import type {User} from './types';

export const roleNames: Record<User['role'], string> = {
  requirement_member: '需求组成员',
  qa_member: 'QA',
  development_member: '开发组成员',
  reviewer: '审核组成员',
  super_admin: '超级管理员',
};

export const roleOptions = Object.entries(roleNames).map(([value,label])=>({value,label}));
