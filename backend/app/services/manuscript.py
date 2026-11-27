"""Document formatting without exposing internal source IDs or repeating chapter wrappers."""
import copy,json,re

CITATION=re.compile(r'[\[【]\s*citation[_ -]?ids?\s*[:：][^\]】\r\n]*[\]】]',re.I)
HEADING=re.compile(r'^\s*(#{1,6})\s+(.+?)\s*#*\s*$')
NUMBER=re.compile(r'^(\d+(?:\.\d+)*)(?:[.、．])?\s*(?=[^\d.])')

def strip_citation_ids(text):
    return CITATION.sub('',text)

def title_text(text):
    return re.sub(r'\s+',' ',re.sub(r'^[#\s]+','',strip_citation_ids(text)).replace('**','')).strip()

def heading_key(text):
    return re.sub(r'\s+','',title_text(text))

def heading_level(title,default=1):
    match=NUMBER.match(title_text(title))
    return min(3,match[1].count('.')+1) if match else min(3,default)


def section_heading(line,explicit):
    """Plain/bold outline titles are boundaries too, but prose/list items are not."""
    match=HEADING.match(line)
    if match:
        return heading_key(match[2]),heading_level(match[2],len(match[1])),title_text(match[2])
    key=heading_key(line)
    if key in explicit:
        title=explicit[key]
        return key,heading_level(title),title
    return None

def section_body(title,content,titles):
    explicit={heading_key(t):title_text(t) for t in titles}
    own=heading_key(title);lines=[];skip_level=None;fenced=False
    for line in strip_citation_ids(content).splitlines():
        if re.match(r'^\s*(```|~~~)',line): fenced=not fenced
        match=section_heading(line,explicit) if not fenced else None
        if match:
            key,level,heading=match
            if skip_level is not None and level<=skip_level: skip_level=None
            if key==own: continue
            if key in explicit:
                skip_level=level;continue
            if skip_level is not None: continue
            line='#'*level+' '+heading
        if skip_level is None: lines.append(line)
    return '\n'.join(lines).strip()


def assemble_sections(sections):
    """A separately generated child owns its content; parent output cannot duplicate it."""
    unique={}
    for section in sections:
        identity=(heading_key(section['title']),strip_citation_ids(section['content']).strip())
        unique.setdefault(identity,section)
    sections=list(unique.values());titles=[s['title'] for s in sections]
    return '\n\n'.join('#'*heading_level(s['title'])+' '+title_text(s['title'])+'\n\n'+section_body(s['title'],s['content'],titles) for s in sections)


def remove_identical_sections(tree):
    """Only remove complete, identical numbered sections in a proposed cleanup.

    Paragraph headings are recognized only when an actual heading with that exact
    title exists. Nested table/list/code text cannot accidentally become a chapter.
    """
    original=tree.get('content',[])
    def text(node):
        if node.get('type')=='hardBreak': return '\n'
        return node.get('text','') if node.get('type')=='text' else ''.join(text(c) for c in node.get('content',[]))
    titles={heading_key(text(n)) for n in original if n.get('type')=='heading' and NUMBER.match(title_text(text(n)))}
    nodes=[]
    for node in original:
        # Markdown soft breaks can put the plain title and its body in one
        # paragraph. Split only a known first-line title, preserving inline marks.
        before=[];after=[];broken=False
        inline=node.get('content',[])
        if node.get('type')=='paragraph' and all(n.get('type') in ('text','hardBreak') for n in inline):
            for child in inline:
                if broken: after.append(child);continue
                if child.get('type')=='hardBreak': broken=True;continue
                left,sep,right=child.get('text','').partition('\n')
                if left: before.append({**child,'text':left})
                if sep:
                    broken=True
                    if right: after.append({**child,'text':right})
            if broken and heading_key(text({'content':before})) in titles:
                nodes.append({**node,'content':before})
                if after: nodes.append({**node,'content':after})
                continue
        nodes.append(node)
    boundaries=[]
    for i,node in enumerate(nodes):
        kind=node.get('type');key=heading_key(text(node))
        if kind=='heading' or kind=='paragraph' and key in titles:
            boundaries.append((i,key,kind=='heading'))
    def semantic(node):
        kind=node.get('type')
        if kind in ('paragraph','heading'):
            links=[m.get('attrs',{}).get('href') for n in node.get('content',[]) for m in n.get('marks',[]) if m.get('type')=='link']
            return [kind,re.sub(r'\s+',' ',strip_citation_ids(text(node))).strip(),links]
        return [kind,node.get('text'),node.get('attrs',{}),[semantic(c) for c in node.get('content',[])]]
    groups={}
    for j,(start,key,heading) in enumerate(boundaries):
        if key not in titles: continue
        end=boundaries[j+1][0] if j+1<len(boundaries) else len(nodes)
        body=[semantic(n) for n in nodes[start+1:end] if not(n.get('type')=='paragraph' and not text(n).strip())]
        if not body: continue
        signature=json.dumps(body,ensure_ascii=False,sort_keys=True)
        groups.setdefault((key,signature),[]).append((start,end,heading))
    drop=set();removed=0
    for group in groups.values():
        if len(group)<2: continue
        keep=max(group,key=lambda entry:(entry[2],entry[0]))
        for entry in group:
            if entry!=keep:
                drop.update(range(entry[0],entry[1]));removed+=1
    if drop: tree['content']=[node for i,node in enumerate(nodes) if i not in drop]
    return removed

def clean_rich_document(value):
    """Keep distinct business content; remove exact repeated chapter bodies only."""
    tree=copy.deepcopy(value);duplicate_sections=remove_identical_sections(tree)
    seen=set();scope={};removed=0;citations=0
    def visit(node):
        nonlocal removed,citations
        # A citation token may span multiple differently formatted text nodes.
        inline=node.get('content',[])
        if inline and all(n.get('type') in ('text','hardBreak') for n in inline):
            text=''.join(n.get('text','') if n.get('type')=='text' else '\n' for n in inline)
            ranges=[m.span() for m in CITATION.finditer(text)]
            citations+=len(ranges);offset=0
            for n in inline:
                original=n.get('text','') if n.get('type')=='text' else '\n'
                if n.get('type')=='text':
                    n['text']=''.join(char for i,char in enumerate(original,offset) if not any(start<=i<end for start,end in ranges))
                offset+=len(original)
        if node.get('type')=='text':
            text=node.get('text','');citations+=len(CITATION.findall(text));node['text']=strip_citation_ids(text)
        children=[]
        for child in node.get('content',[]):
            if child.get('type')=='heading':
                text=''.join(n.get('text','') for n in child.get('content',[]));key=heading_key(text)
                level=heading_level(text,(child.get('attrs') or {}).get('level',1))
                numbered=bool(NUMBER.match(title_text(text)))
                identity=key if numbered or level==1 else tuple(scope.get(i,'') for i in range(1,level))+(key,)
                if identity in seen:
                    removed+=1;continue
                seen.add(identity);scope[level]=key
                for i in list(scope):
                    if i>level: del scope[i]
                child['attrs']={**child.get('attrs',{}),'level':level}
            visit(child)
            if child.get('type')!='text' or child.get('text'): children.append(child)
        if 'content' in node: node['content']=children
    visit(tree)
    issues={'duplicate_headings':removed,'citation_markers':citations}
    if duplicate_sections: issues['duplicate_sections']=duplicate_sections
    return tree,issues
