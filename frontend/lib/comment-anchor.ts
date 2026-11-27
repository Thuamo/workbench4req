export type CommentAnchor = {offset: number; before: string; after: string};
export type CommentTarget = {quote: string; anchor?: CommentAnchor | null};

function normalize(text: string) {return text.replace(/\s/g, '');}

export function indexCommentText(root: HTMLElement) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const parts: {node: Text; start: number; end: number}[] = [];
  const chunks: string[] = [];
  let offset = 0;
  for (let current = walker.nextNode(); current; current = walker.nextNode()) {
    const node = current as Text;
    const text = normalize(node.data);
    if (!text) continue;
    parts.push({node, start:offset, end:offset+text.length});
    offset += text.length;
    chunks.push(text);
  }
  return {text:chunks.join(''), parts};
}

export function selectedCommentTarget(root: HTMLElement | null): CommentTarget {
  const selection = window.getSelection();
  if (!root || !selection?.rangeCount || selection.isCollapsed) return {quote:''};
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return {quote:''};
  const quote = Array.from(selection.toString().trim()).slice(0,2000).join('');
  const wanted = normalize(quote);
  if (!wanted) return {quote:''};
  const prefix = range.cloneRange();
  prefix.selectNodeContents(root);
  prefix.setEnd(range.startContainer,range.startOffset);
  const offset = normalize(prefix.toString()).length;
  const text = indexCommentText(root).text;
  if (!text.startsWith(wanted,offset)) return {quote};
  const end = offset+wanted.length;
  const before = text.slice(Math.max(0,offset-48),offset).replace(/^[\uDC00-\uDFFF]/,'');
  const after = text.slice(end,end+48).replace(/[\uD800-\uDBFF]$/,'');
  return {quote,anchor:{offset,before,after}};
}

function matchOffset(text: string, wanted: string, anchor?: CommentAnchor | null) {
  const first = text.indexOf(wanted);
  if (first === -1) return -1;
  if (!anchor || (!anchor.before && !anchor.after)) return text.indexOf(wanted,first+1)===-1 ? first : -1;

  let strongest = 0;
  let position = -1;
  for (let offset = first; offset !== -1; offset = text.indexOf(wanted,offset+1)) {
    const before = anchor.before && text.slice(Math.max(0,offset-anchor.before.length),offset)===anchor.before;
    const after = anchor.after && text.startsWith(anchor.after,offset+wanted.length);
    const context = Number(Boolean(before))+Number(Boolean(after));
    if (!context) continue;
    const score = context*2+Number(offset===anchor.offset);
    if (score>strongest) {strongest=score;position=offset;}
    else if (score===strongest) position=-1;
  }
  return position;
}

function rawOffset(text: string, index: number) {
  for (let offset=0;offset<text.length;offset++) {
    if (!/\s/.test(text[offset]) && index--===0) return offset;
  }
  return text.length;
}

export function commentRange(index: ReturnType<typeof indexCommentText>, target: CommentTarget) {
  const wanted = normalize(target.quote);
  if (!wanted) return null;
  const startOffset = matchOffset(index.text,wanted,target.anchor);
  if (startOffset===-1) return null;
  const endOffset = startOffset+wanted.length-1;
  const first = index.parts.find(part=>startOffset>=part.start && startOffset<part.end);
  const last = index.parts.find(part=>endOffset>=part.start && endOffset<part.end);
  if (!first || !last) return null;
  const range = document.createRange();
  range.setStart(first.node,rawOffset(first.node.data,startOffset-first.start));
  range.setEnd(last.node,rawOffset(last.node.data,endOffset-last.start)+1);
  return range;
}

export function locateComment(root: HTMLElement | null, target: CommentTarget) {
  const selection = window.getSelection();
  if (!root || !selection) return false;
  const range = commentRange(indexCommentText(root),target);
  if (!range) return false;
  selection.removeAllRanges();
  selection.addRange(range);
  range.startContainer.parentElement?.scrollIntoView({block:'center'});
  return true;
}
