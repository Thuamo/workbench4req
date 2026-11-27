import {Extension,type Editor,type JSONContent} from '@tiptap/core';

export const alignments=[
  {value:'left',label:'靠左'},
  {value:'center',label:'居中'},
  {value:'right',label:'靠右'},
] as const;

function supported(value:unknown) {
  return alignments.some(alignment=>alignment.value===value);
}

export function editorContent(editor:Editor):JSONContent {
  const content=editor.getJSON();
  // Preserve the stored shape of nodes with default alignment.
  function serializeAlignment(node:JSONContent) {
    if(node.attrs && 'textAlign' in node.attrs){
      const {textAlign,...attrs}=node.attrs;
      if(textAlign!==null)attrs.textAlign=textAlign;
      if(Object.keys(attrs).length)node.attrs=attrs;
      else delete node.attrs;
    }
    node.content?.forEach(serializeAlignment);
  }
  serializeAlignment(content);
  return content;
}

export const DocumentAlignment=Extension.create({
  name:'documentAlignment',
  addGlobalAttributes() {
    return [{
      types:['paragraph','heading'],
      attributes:{
        textAlign:{
          default:null,
          parseHTML:element=>{
            const value=element.style.textAlign||element.getAttribute('align');
            return supported(value)?value:null;
          },
          renderHTML:attributes=>supported(attributes.textAlign)?{style:'text-align: '+attributes.textAlign}:{},
        },
      },
    },{
      types:['image'],
      attributes:{
        textAlign:{
          default:null,
          parseHTML:element=>supported(element.dataset.align)?element.dataset.align:null,
          renderHTML:attributes=>supported(attributes.textAlign)?{'data-align':attributes.textAlign}:{},
        },
      },
    }];
  },
});
