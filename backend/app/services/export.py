import io, re
from fastapi import HTTPException
from docx import Document as Word
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from ..models import DocumentVersion, Document
from .files import blob
from .richtext import IMAGE_MARKDOWN


def inline(paragraph,text,pictures,max_width,max_height):
    """Preserve common editor marks instead of exporting literal Markdown tokens."""
    for piece in re.split(r'(!\[[^\]\r\n]*\]\(/api/document-images/[0-9a-f-]+\)|\*\*[^*]+\*\*|(?<!\*)\*[^*]+\*(?!\*)|`[^`]+`)',text):
        if not piece:continue
        reference=IMAGE_MARKDOWN.fullmatch(piece)
        if reference and reference[2] in pictures:
            image=pictures[reference[2]]
            scale=min(Inches(1)/96,max_width/image.width,max_height/image.height)
            path=blob(image.file_hash)
            if not path.is_file(): raise HTTPException(409,'软需图片文件不可用，无法导出完整文档')
            shape=paragraph.add_run().add_picture(str(path),width=max(1,int(image.width*scale)),height=max(1,int(image.height*scale)))
            shape._inline.docPr.set('descr',reference[1])
        elif piece.startswith('**') and piece.endswith('**'):paragraph.add_run(piece[2:-2]).bold=True
        elif piece.startswith('*') and piece.endswith('*'):paragraph.add_run(piece[1:-1]).italic=True
        elif piece.startswith('`') and piece.endswith('`'):paragraph.add_run(piece[1:-1]).font.name='Consolas'
        else:paragraph.add_run(piece)

def add_table(doc,rows: list[list[str]],pictures,max_height):
    width=max(len(row) for row in rows)
    result=doc.add_table(rows=0,cols=width)
    result.style='Table Grid'
    result.autofit=False
    for index,row in enumerate(rows):
        cells=result.add_row().cells
        result.rows[-1]._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for column,cell in enumerate(cells):
            section=doc.sections[0]
            cell.width=int((section.page_width-section.left_margin-section.right_margin)/width)
            inline(cell.paragraphs[0],row[column].replace('<br>','\n') if column<len(row) else '',pictures,cell.width,max_height)
        if index==0:
            repeat=OxmlElement('w:tblHeader')
            result.rows[0]._tr.get_or_add_trPr().append(repeat)
            for cell in cells:
                cell.paragraphs[0].paragraph_format.keep_with_next=True
                for run in cell.paragraphs[0].runs:
                    run.bold=True
    doc.add_paragraph()


def export_docx(document: Document,version: DocumentVersion,pictures=None) -> bytes:
    pictures=pictures or {}
    doc=Word()
    template_id=version.provenance.get('word_template_version_id')
    if template_id:
        from ..db import SessionLocal
        with SessionLocal() as db:
            template=db.get(DocumentVersion,template_id)
            if not template or not template.filename.lower().endswith('.docx'):raise HTTPException(409,'原排版模板不可用，请重新选择模板并确认版本')
            try:doc=Word(io.BytesIO(blob(template.file_hash).read_bytes()))
            except Exception:raise HTTPException(409,'排版模板读取失败，请核对 DOCX 模板')
        # Retain section layout, styles, headers, footers and logos. Never copy
        # the template's example business text into the delivered requirements.
        body=doc._element.body
        for child in list(body):
            if child.tag!=qn('w:sectPr'):body.remove(child)
    # Explicitly remove inherited title decoration from the runtime's default template.
    for style in doc.styles:
        if template_id:continue
        for border in style.element.xpath('.//w:pBdr'):
            border.getparent().remove(border)
    s=doc.sections[0]
    page=version.provenance.get('delivery_template',{}).get('page',{})
    if not template_id:
        standard=page.get('size')=='A4'
        s.page_width=Cm(21) if standard else Inches(8.5)
        s.page_height=Cm(29.7) if standard else Inches(11)
        s.top_margin=s.bottom_margin=s.left_margin=s.right_margin=Cm(page.get('margin_cm',2.54))
    for name,size in [('Normal',11),('Title',20),('Heading 1',16),('Heading 2',14),('Heading 3',12)]:
        if template_id:continue
        style=doc.styles[name]
        style.font.name=page.get('font','等线')
        style.font.size=Pt(page.get('size_pt',size) if name=='Normal' else size)
        style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),page.get('font','等线'))
        style.paragraph_format.line_spacing=1.2
        style.paragraph_format.space_after=Pt(4)
    doc.add_paragraph(document.title,style='Title')
    doc.add_paragraph(f'版本 {version.label}　'+('正式发布版本' if version.publish_status=='published' else '草稿 待人工审核'))
    table=doc.add_table(rows=1,cols=2)
    table.style='Table Grid'
    table.rows[0].cells[0].text='项目'
    table.rows[0].cells[1].text='内容'
    for k,v in [('版本标识',version.id),('变更说明',version.change_note),('来源与质量检查','；'.join(version.warnings) or '请核对业务内容和来源引用')]:
        cells=table.add_row().cells
        cells[0].text=k
        cells[1].text=v
    rows=[]
    max_width=s.page_width-s.left_margin-s.right_margin
    max_height=s.page_height-s.top_margin-s.bottom_margin-Cm(1)
    def add_content(paragraph,text):
        inline(paragraph,text,pictures,max_width,max_height)
    def flush():
        if rows:
            add_table(doc,rows,pictures,max_height)
            rows.clear()
    for line in version.content.splitlines():
        line=line.strip()
        if line.startswith('|') and line.endswith('|'):
            cells=[cell.strip() for cell in re.split(r'(?<!\\)\|',line[1:-1])]
            if not all(re.fullmatch(r'[-: ]+',cell) for cell in cells):
                rows.append([cell.replace('\\|','|') for cell in cells])
            continue
        flush()
        if not line:
            continue
        heading=re.match(r'^(#{1,3})\s+(.+)',line)
        if heading:
            add_content(doc.add_paragraph(style=f'Heading {len(heading[1])}'),heading[2])
        elif re.match(r'^\d+(?:\.\d+)*\s+\S',line) and len(line)<65:
            depth=min(3,line.split()[0].count('.')+1)
            doc.add_paragraph(line,style=f'Heading {depth}')
        else:
            numbered=re.match(r'^\d+\.\s+(.+)',line)
            bullet=re.match(r'^[-*]\s+(.+)',line)
            if bullet:add_content(doc.add_paragraph(style='List Bullet'),bullet[1])
            elif numbered:add_content(doc.add_paragraph(style='List Number'),numbered[1])
            else:add_content(doc.add_paragraph(),line)
    flush()
    sources=version.provenance.get('sources',[])
    if sources:
        doc.add_paragraph('来源与版本追溯',style='Heading 1')
        for index,source in enumerate(sources,1):
            doc.add_paragraph(f"[{index}] {source.get('title','来源')} {source.get('version','')}；{source.get('locator','')}；版本 ID：{source.get('document_version_id',source.get('citation_id',''))}")
    output=io.BytesIO()
    doc.save(output)
    return output.getvalue()
