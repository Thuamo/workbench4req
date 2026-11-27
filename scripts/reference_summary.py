import json, collections, re
from pathlib import Path
from docx import Document
root=Path(__file__).resolve().parents[1]
records=json.loads((root/'docs/reference-extraction.json').read_text(encoding='utf-8'))
for r in records:
    print('\nFILE:',r['path'])
    if 'sheets' in r:
        for s in r['sheets']:
            print('SHEET:',s['name'],s['rows'],s['columns'],'FIELDS:',s['data'][0])
            print('NONEMPTY ROWS:',sum(bool(row[0]) for row in s['data'][1:]))
            print('DUPLICATES:',[x for x,n in collections.Counter(row[0] for row in s['data'][1:] if row[0]).items() if n>1])
            for col in [9,13,23]:print('VALUES:',s['data'][0][col],collections.Counter(str(row[col]) for row in s['data'][1:] if row[0]))
    elif 'paragraphs' in r:
        print('PARAGRAPHS:',len(r['paragraphs']),'TABLES:',len(r['tables']))
        print('HEADINGS:',[p['text'] for p in r['paragraphs'] if re.match(r'^\d+(?:\.\d+)*[ .、]',p['text']) and len(p['text'])<40])
        print('ENDING:',[p['text'] for p in r['paragraphs'][-8:]])
styles=[]
for p in (root/'reference_files').rglob('*.docx'):
    d=Document(p)
    styles.append({'path':str(p.relative_to(root)), 'sections':[{'width':s.page_width.cm if s.page_width else None,'height':s.page_height.cm if s.page_height else None} for s in d.sections], 'runs':[{'text':r.text[:60],'font':r.font.name,'size':r.font.size.pt if r.font.size else None,'bold':r.bold} for para in d.paragraphs[:15] for r in para.runs if r.text], 'paragraph_format':[{'text':para.text[:60], 'line':str(para.paragraph_format.line_spacing),'after':str(para.paragraph_format.space_after)} for para in d.paragraphs[:15]]})
(root/'docs/reference-styles.json').write_text(json.dumps(styles,ensure_ascii=False,indent=2),encoding='utf-8')
print('\nSTYLES:',json.dumps(styles[-3:],ensure_ascii=False)[:4500])
