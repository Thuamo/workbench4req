"""Incrementally expose claim text without exposing the model's JSON envelope.

Only direct claims[].text string values are displayed. Keys, citation IDs,
evidence quotes and other fields remain private protocol data. Final validation
still uses the complete original JSON, never the partial preview.
"""


class ClaimTextStream:
    def __init__(self):
        self.stack=[]
        self.started=False
        self.invalid=False
        self.in_string=False
        self.is_key=False
        self.visible=False
        self.value=''
        self.escape=False
        self.unicode=None
        self.high=None
        self.primitive=False
        self.claims=0
        self.output=[]

    def _finish_value(self):
        if self.stack: self.stack[-1]['expect']='comma'

    def _character(self,ch):
        code=ord(ch)
        if self.high is not None:
            if 0xDC00<=code<=0xDFFF:
                ch=chr(0x10000+((self.high-0xD800)<<10)+(code-0xDC00));self.high=None
            else:
                self.high=None;self._character('\uFFFD')
        elif 0xDC00<=code<=0xDFFF:
            ch='\uFFFD'
        if 0xD800<=code<=0xDBFF:
            self.high=code;return
        if self.is_key: self.value+=ch
        if self.visible:
            frame=self.stack[-1]
            if not frame.get('displayed'):
                self.output.append('\n\n- ' if self.claims else '- ')
                self.claims+=1;frame['displayed']=True
            self.output.append(ch)

    def feed(self,chunk):
        self.output=[]
        for ch in chunk:
            if self.invalid: break
            if self.in_string:
                if self.unicode is not None:
                    if ch not in '0123456789abcdefABCDEF': self.invalid=True;break
                    self.unicode+=ch
                    if len(self.unicode)==4:
                        value=chr(int(self.unicode,16));self.unicode=None;self._character(value)
                elif self.escape:
                    self.escape=False
                    if ch=='u': self.unicode=''
                    elif ch in '"\\/bfnrt': self._character({'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'}[ch])
                    else: self.invalid=True;break
                elif ch=='\\': self.escape=True
                elif ch=='"':
                    if self.high is not None: self.high=None;self._character('\uFFFD')
                    self.in_string=False
                    if self.is_key:
                        self.stack[-1]['key']=self.value;self.stack[-1]['expect']='colon'
                    else: self._finish_value()
                elif ord(ch)<0x20:
                    self.invalid=True;break
                else: self._character(ch)
                continue
            if self.primitive:
                if ch not in ',]} \t\r\n': continue
                self.primitive=False;self._finish_value()
            if ch.isspace(): continue
            if not self.started:
                # Tolerate a Markdown fence. The full validator decides validity.
                if ch!='{': continue
                self.started=True
            parent=self.stack[-1] if self.stack else None
            if ch=='{':
                role='root' if not parent else 'claim' if parent['role']=='claims' else 'other'
                self.stack.append({'type':'object','role':role,'expect':'key','key':None})
            elif ch=='[':
                role='claims' if parent and parent['role']=='root' and parent['key']=='claims' and parent['expect']=='value' else 'other'
                self.stack.append({'type':'array','role':role,'expect':'value','key':None})
            elif ch in '}]':
                if not parent or parent['type']!=('object' if ch=='}' else 'array'): self.invalid=True;break
                self.stack.pop();self._finish_value()
            elif ch=='"':
                if not parent: self.invalid=True;break
                self.in_string=True;self.is_key=parent['type']=='object' and parent['expect']=='key'
                self.visible=not self.is_key and parent['role']=='claim' and parent['key']=='text' and parent['expect']=='value'
                self.value='';self.escape=False;self.unicode=None;self.high=None
            elif ch==':':
                if not parent or parent['expect']!='colon': self.invalid=True;break
                parent['expect']='value'
            elif ch==',':
                if not parent or parent['expect']!='comma': self.invalid=True;break
                parent['expect']='key' if parent['type']=='object' else 'value';parent['key']=None
            elif ch in '-0123456789tfn': self.primitive=True
            else: self.invalid=True;break
        return ''.join(self.output)
