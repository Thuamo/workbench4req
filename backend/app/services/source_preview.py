import csv
import io
from functools import lru_cache
from itertools import islice
from pathlib import Path
from subprocess import TimeoutExpired

from fastapi import HTTPException

from .files import isolated_parse, store

SPREADSHEET_SUFFIXES = {'.xlsx', '.xls', '.csv'}
IMAGE_HEADERS = {
    'image/png': (b'\x89PNG\r\n\x1a\n',), 'image/jpeg': (b'\xff\xd8\xff',),
    'image/gif': (b'GIF87a', b'GIF89a'), 'image/webp': (b'RIFF',), 'image/bmp': (b'BM',),
}
PAGE_SIZE = 50


@lru_cache(maxsize=24)
def source_preview(file_hash, filename, sheet=0, offset=0, page=0):
    try:
        return isolated_parse(file_hash, filename, 'preview', str(sheet), str(offset), str(page))
    except TimeoutExpired as error:
        raise HTTPException(422, '原文件预览超时，请下载原件查看') from error
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(422, '原文件预览失败，请下载原件查看') from error


def spreadsheet_preview(path, suffix, sheet, offset):
    def response(sheets, rows, columns, has_more, total_columns):
        return {'kind': 'spreadsheet', 'sheets': sheets, 'sheet': sheet, 'offset': offset,
                'rows': [['' if cell is None else str(cell) for cell in row] for row in rows],
                'columns': columns, 'has_more': has_more, 'columns_limited': total_columns > columns}

    if suffix == '.xlsx':
        from openpyxl import load_workbook
        with path.open('rb') as stream:
            workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
            try:
                sheets = workbook.sheetnames
                if sheet==-1:
                    sheet = sheets.index(workbook.active.title) if workbook.active else 0
                current = workbook.worksheets[sheet]
                columns = min(current.max_column or 100, 200)
                last_row = min(current.max_row or offset+PAGE_SIZE+1, offset+PAGE_SIZE+1)
                rows = list(islice(current.iter_rows(min_row=offset+1, max_row=last_row,
                                                     max_col=columns, values_only=True), PAGE_SIZE+1))
                return response(sheets, rows[:PAGE_SIZE], columns, len(rows)>PAGE_SIZE,
                                current.max_column or columns)
            finally:
                workbook.close()
    if sheet==-1:
        sheet = 0
    if suffix == '.xls':
        import xlrd
        workbook = xlrd.open_workbook(file_contents=path.read_bytes(), on_demand=True)
        try:
            current = workbook.sheet_by_index(sheet)
            columns = min(current.ncols, 200)
            rows = [current.row_values(row, end_colx=columns) for row in range(offset, min(current.nrows, offset+PAGE_SIZE))]
            return response(workbook.sheet_names(), rows, columns, offset+PAGE_SIZE<current.nrows, current.ncols)
        finally:
            workbook.release_resources()
    if sheet!=0:
        raise ValueError('Invalid CSV sheet')
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('gb18030')
    rows = list(islice(csv.reader(io.StringIO(text)), offset, offset+PAGE_SIZE+1))
    width = max((len(row) for row in rows), default=0)
    columns = min(width, 200)
    return response(['CSV'], [row[:columns] for row in rows[:PAGE_SIZE]], columns, len(rows)>PAGE_SIZE, width)


def word_preview(path):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run

    images = []
    image_ids = {}
    omitted = 0

    def picture(element, drawing):
        nonlocal omitted
        relationship = element.part.rels.get(drawing.get(qn('r:embed')))
        if relationship is None or relationship.is_external:
            omitted += 1
            return None
        part = relationship.target_part
        headers = IMAGE_HEADERS.get(part.content_type, ())
        if (not part.blob.startswith(headers) or len(part.blob)>10*1024*1024 or
                part.content_type=='image/webp' and part.blob[8:12]!=b'WEBP'):
            omitted += 1
            return None
        key = str(part.partname)
        if key not in image_ids:
            image_ids[key] = len(images)
            images.append({'hash': store(part.blob), 'type': part.content_type})
        return image_ids[key]

    def paragraph(element):
        parts = []
        for node in element._p.xpath('./w:r | ./w:hyperlink/w:r'):
            text = Run(node, element).text
            if text:
                parts.append(text)
            for drawing in node.xpath('.//a:blip'):
                index = picture(element, drawing)
                if index is not None:
                    parts.append(index)
        style = element.style.name if element.style else ''
        heading = style.lower().startswith('heading')
        return {'kind': 'text', 'parts': parts,
                'heading': heading, 'align': getattr(element.alignment,'name','').lower()}

    def block(element):
        if isinstance(element, Paragraph):
            return paragraph(element)
        return {'kind': 'table', 'rows': [
            [[block(inner) for inner in cell.iter_inner_content()] for cell in row.cells]
            for row in element.rows
        ]}

    document = Document(path)
    blocks = [block(element) for element in document.iter_inner_content()]
    return {'kind': 'word', 'blocks': blocks, 'images': images, 'omitted_images': omitted}


def preview_file(path: Path, suffix: str, sheet: int, offset: int, page: int):
    if suffix in SPREADSHEET_SUFFIXES:
        return spreadsheet_preview(path, suffix, sheet, offset)
    if suffix in ('.docx', '.doc'):
        if suffix == '.docx':
            return word_preview(path)
        from tempfile import TemporaryDirectory
        from .files import convert_word
        with TemporaryDirectory() as directory:
            return word_preview(convert_word(path, Path(directory)))
    if suffix == '.pdf':
        import pymupdf as fitz
        with fitz.open(path) as pdf:
            if not page:
                return {'kind': 'pdf', 'pages': len(pdf)}
            current = pdf[page-1]
            scale = min(2, 1500/max(1, current.rect.width, current.rect.height))
            image = current.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
            return {'hash': store(image), 'type': 'image/png'}
    raise ValueError('Unsupported source format')
