import {isDocumentImageUrl} from './document-image';

const IMAGES = ['image/png', 'image/jpeg'];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_TABLE_CELLS = 10000;
const unsupportedImage = '剪贴板没有可读取的图片。请复制 PNG 或 JPEG 图片本身后重试。';
const oversizedTable = () => new Error('表格过大，请拆分后粘贴。');
const imageFilename = /\.(?:png|jpe?g)$/i;

export function clipboardImages(clipboard:DataTransfer):File[] {
  const files = Array.from(clipboard.files);
  return (files.length ? files : Array.from(clipboard.items, item=>item.getAsFile()))
    .filter((file):file is File=>!!file && (file.type.startsWith('image/') || imageFilename.test(file.name)));
}

export async function imageFromClipboardElement(element:HTMLImageElement, fallback?:File):Promise<File> {
  const source = element.getAttribute('src') || '';
  const dataUrl = /^data:(image\/(?:png|jpeg));base64,([a-z0-9+/=\s]+)$/i.exec(source);
  let blob:Blob;
  if (dataUrl) {
    const encoded = dataUrl[2].replace(/\s/g,'');
    if (encoded.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4) throw new Error('图片大小不能超过 10 MB。');
    blob = new Blob([Uint8Array.from(atob(encoded), char=>char.charCodeAt(0))], {type:dataUrl[1].toLowerCase()});
  } else {
    const url = source ? URL.parse(source,window.location.href) : null;
    if (!url || url.origin!==window.location.origin || !isDocumentImageUrl(url.pathname)) {
      if (fallback) return fallback;
      throw new Error(unsupportedImage);
    }
    const response = await fetch(url.pathname, {credentials:'same-origin'});
    if (!response.ok) throw new Error('原图片无法读取，请复制图片本身后重试。');
    blob = await response.blob();
  }
  const name = element.getAttribute('alt')?.trim() || (blob.type==='image/jpeg' ? '粘贴图片.jpg' : '粘贴图片.png');
  return new File([blob],name,{type:blob.type});
}

export function validateClipboardImage(file:File) {
  if (!IMAGES.includes(file.type) && (file.type || !imageFilename.test(file.name))) throw new Error(unsupportedImage);
  if (file.size > MAX_IMAGE_BYTES) throw new Error('图片大小不能超过 10 MB。');
}

export function clipboardMarkup(html:string) {
  const template=document.createElement('template');
  template.innerHTML=html;
  template.content.querySelectorAll('script,style,link,meta,object,embed,iframe').forEach(node=>node.remove());
  return template;
}

export function normalizeClipboardTables(root:DocumentFragment) {
  let changed=false;
  for (const table of root.querySelectorAll('table')) {
    const rows=Array.from(table.rows);
    if (!rows.some(row=>Array.from(row.cells).some(cell=>cell.colSpan!==1||cell.rowSpan!==1))) continue;
    // The stored table format uses a rectangular grid. Keep a merged cell's
    // contents in its first position and fill the remaining positions with cells.
    const grid:HTMLTableCellElement[][]=rows.map(()=>[]);
    let width=0;
    rows.forEach((row,y)=>{
      let column=0;
      for (const cell of Array.from(row.cells)) {
        while (grid[y][column]) column++;
        const columns=cell.colSpan;
        const height=Math.min(cell.rowSpan||rows.length-y,rows.length-y);
        width=Math.max(width,column+columns);
        if (rows.length*width>MAX_TABLE_CELLS) throw oversizedTable();
        cell.removeAttribute('rowspan');
        cell.removeAttribute('colspan');
        cell.removeAttribute('colwidth');
        for(let cy=y;cy<y+height;cy++) {
          for(let cx=column;cx<column+columns;cx++) {
            if (grid[cy][cx]) throw new Error('表格的合并单元格重叠，请在原表中调整后再粘贴。');
            grid[cy][cx]=cy===y&&cx===column?cell:document.createElement(cell.tagName.toLowerCase()) as HTMLTableCellElement;
          }
        }
        column+=columns;
      }
    });
    rows.forEach((row,y)=>row.replaceChildren(...Array.from({length:width},(_,x)=>grid[y][x]||document.createElement('td'))));
    changed=true;
  }
  return changed;
}

export function clipboardTextTable(text:string):HTMLTableElement|null {
  if (!text.includes('\t')) return null;
  // Spreadsheet clipboard text quotes fields containing line breaks or tabs.
  const rows:string[][]=[[]];
  let value='', quoted=false;
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if (char==='"' && (quoted || !value)) {
      if (quoted && text[i+1]==='"') {value+='"';i++;}
      else quoted=!quoted;
    } else if (!quoted && (char==='\t'||char==='\n'||char==='\r')){
      rows[rows.length-1].push(value);
      value='';
      if (char!=='\t'){
        if(char==='\r'&&text[i+1]==='\n')i++;
        if(i<text.length-1)rows.push([]);
        else break;
      }
    } else value+=char;
    if(i===text.length-1) rows[rows.length-1].push(value);
  }
  const width=rows.reduce((max,row)=>Math.max(max,row.length),0);
  if(width<2||quoted)return null;
  if(rows.length*width>MAX_TABLE_CELLS)throw oversizedTable();
  const table=document.createElement('table');
  for(const row of rows){
    const tr=table.insertRow();
    for(let i=0;i<width;i++){
      const cell=tr.insertCell();
      (row[i]||'').split(/\r\n?|\n/).forEach((line,index)=>{
        if(index)cell.append(document.createElement('br'));
        cell.append(line);
      });
    }
  }
  return table;
}

