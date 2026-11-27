"""Validate the editor's document tree and derive the read/search representation."""
import json
import re
from fastapi import HTTPException

NODES={'doc','paragraph','text','heading','bulletList','orderedList','listItem','blockquote','codeBlock','hardBreak','horizontalRule','table','tableRow','tableCell','tableHeader','image'}
MARKS={'bold','italic','strike','code','link','underline'}
IMAGE_URL = r'/api/document-images/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})'
IMAGE_MARKDOWN = re.compile(r'!\[([^\]\r\n]*)\]\(' + IMAGE_URL + r'\)')


def image_ids(content):
    return list(dict.fromkeys(match[2] for match in IMAGE_MARKDOWN.finditer(content)))


def rich_content(value):
    count=0
    def clean(node,depth=0):
        nonlocal count
        count+=1
        if depth>40 or count>100000 or not isinstance(node,dict) or node.get('type') not in NODES:
            raise ValueError()
        kind=node['type'];out={'type':kind}
        if kind=='text':
            if not isinstance(node.get('text'),str): raise ValueError()
            out['text']=node['text']
        attrs=node.get('attrs') or {}
        if not isinstance(attrs,dict): raise ValueError()
        if kind=='image':
            src=attrs.get('src')
            alt=attrs.get('alt') or ''
            if not isinstance(src,str) or not re.fullmatch(IMAGE_URL,src) or not isinstance(alt,str) or len(alt)>300:
                raise ValueError()
            if node.get('content') or node.get('marks'): raise ValueError()
            out['attrs']={'src':src,'alt':alt}
        if kind=='heading': out['attrs']={'level':max(1,min(3,int(attrs.get('level',1))))}
        if kind in ('paragraph','heading','image') and (alignment:=attrs.get('textAlign')) is not None:
            if alignment not in ('left','center','right'): raise ValueError()
            out.setdefault('attrs',{})['textAlign']=alignment
        if kind=='image': return out
        if kind=='orderedList': out['attrs']={'start':max(1,int(attrs.get('start',1)))}
        if kind in ('tableCell','tableHeader'):
            # Complex merged cells are a later feature; never silently flatten them.
            if attrs.get('colspan',1)!=1 or attrs.get('rowspan',1)!=1: raise ValueError()
        if 'content' in node:
            if not isinstance(node['content'],list): raise ValueError()
            out['content']=[clean(n,depth+1) for n in node['content']]
        if node.get('marks'):
            marks=[]
            for mark in node['marks']:
                if not isinstance(mark,dict) or mark.get('type') not in MARKS: raise ValueError()
                m={'type':mark['type']}
                if m['type']=='link':
                    href=str((mark.get('attrs') or {}).get('href',''))
                    if not re.match(r'^(https?://|mailto:|#)',href,re.I): raise ValueError()
                    m['attrs']={'href':href,'target':'_blank','rel':'noopener noreferrer'}
                marks.append(m)
            out['marks']=marks
        return out
    try:
        if len(json.dumps(value,ensure_ascii=False))>8000000 or not isinstance(value,dict) or value.get('type')!='doc': raise ValueError()
        tree=clean(value)
        text=render(tree).strip()
        if len(text)>2000000: raise ValueError()
        return tree,text
    except (ValueError,TypeError,RecursionError,OverflowError):
        raise HTTPException(422,'富文本内容无效、包含不支持的格式或超过限制')


def render(node):
    kind=node['type'];children=node.get('content',[])
    if kind=='text':
        text=node.get('text','')
        for mark in node.get('marks',[]):
            t=mark['type']
            if t in ('bold','italic','strike','code'):
                token={'bold':'**','italic':'*','strike':'~~','code':'`'}[t];text=token+text+token
            elif t=='link': text='['+text+']('+mark['attrs']['href']+')'
        return text
    if kind=='hardBreak': return '\n'
    if kind=='image':
        attrs=node['attrs']
        alt=re.sub(r'[\[\]\\\r\n|]', ' ', attrs['alt'])
        return f"![{alt}]({attrs['src']})"
    if kind=='horizontalRule': return '---'
    if kind=='table':
        rows=[]
        for row in children:
            rows.append([render(cell).strip().replace('|','\\|').replace('\n','<br>') for cell in row.get('content',[])])
        if not rows: return ''
        return '\n'.join(['| '+' | '.join(rows[0])+' |','| '+' | '.join(['---']*len(rows[0]))+' |',*['| '+' | '.join(r)+' |' for r in rows[1:]]])
    if kind in ('bulletList','orderedList'):
        start=node.get('attrs',{}).get('start',1)
        return '\n'.join((('- ' if kind=='bulletList' else str(start+i)+'. ')+render(item).replace('\n','\n  ')) for i,item in enumerate(children))
    sep='\n\n' if kind in ('doc','blockquote','listItem','tableCell','tableHeader') else ''
    text=sep.join(render(n) for n in children)
    if kind=='heading': return '#'*node.get('attrs',{}).get('level',1)+' '+text
    if kind=='blockquote': return '\n'.join('> '+line for line in text.splitlines())
    if kind=='codeBlock': return '```\n'+text+'\n```'
    return text
