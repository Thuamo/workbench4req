import {Node} from '@tiptap/core';

const imageUrl = /^\/api\/document-images\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
export const isDocumentImageUrl = (src:string) => imageUrl.test(src);

export type SpecificationImage = {src: string; alt: string};

export const DocumentImage = Node.create({
  name: 'image',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,
  addAttributes() {return {src:{default:null}, alt:{default:''}};},
  parseHTML() {
    return [{tag:'img[src]',getAttrs:element=>isDocumentImageUrl(element.getAttribute('src')||'') ? null : false}];
  },
  renderHTML({HTMLAttributes}) {
    const {src,...attributes}=HTMLAttributes;
    return ['img',{...attributes,src:isDocumentImageUrl(src||'') ? src : undefined,draggable:'true'}];
  },
  parseMarkdown(token, helpers) {
    return isDocumentImageUrl(token.href||'') ? helpers.createNode('image',{src:token.href,alt:token.text||''}) : [];
  },
  renderMarkdown(node) {
    if (!isDocumentImageUrl(node.attrs?.src||'')) return '';
    const alt=String(node.attrs?.alt||'').replace(/[\[\]\\\r\n|]/g,' ');
    return `![${alt}](${node.attrs?.src})`;
  },
});
