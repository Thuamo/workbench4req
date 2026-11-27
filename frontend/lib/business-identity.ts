import type {Requirement} from './types';
export function requirementLabel(r:Requirement){
 const scope=[...(r.tags?.['系统']||[]),...(r.tags?.['项目']||[])];
 return r.number+' '+r.title+(scope.length?' · '+scope.join(' / '):'');
}
