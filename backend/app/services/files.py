import csv, io, json, re, zipfile, subprocess, sys, tempfile, os, posixpath
from pathlib import Path
from xml.etree import ElementTree as ET
from shutil import which
from fastapi import HTTPException
from ..config import settings
from ..security import digest

ALLOWED = {
    '.pdf','.docx','.doc','.xlsx','.xls','.pptx','.txt','.md','.csv',
    '.py','.java','.kt','.cs','.js','.jsx','.ts','.tsx','.go','.rs','.cpp','.c','.h',
    '.json','.yaml','.yml','.toml','.xml','.sql','.puml','.plantuml','.mmd',
}


def store(data: bytes) -> str:
    file_hash = digest(data)
    path = settings.storage_dir/'blobs'/file_hash[:2]/file_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic immutable creation; another identical upload shares bytes, never ownership.
    try:
        with path.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        if digest(path.read_bytes()) != file_hash:
            raise RuntimeError('存储哈希校验失败')
    return file_hash


def blob(file_hash: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{64}', file_hash):
        raise HTTPException(400, '无效文件哈希')
    return settings.storage_dir/'blobs'/file_hash[:2]/file_hash


def validate(data: bytes, filename: str) -> str:
    name = filename.replace('\\','/').split('/')[-1]
    suffix = Path(name).suffix.lower()
    if not name or len(name)>300 or suffix not in ALLOWED:
        raise HTTPException(422, '不支持的文件格式')
    if not data or len(data)>settings.upload_limit_mb*1024*1024:
        raise HTTPException(413, '文件为空或超过大小限制')
    office_parts={'.docx':'word/document.xml','.xlsx':'xl/workbook.xml','.pptx':'ppt/presentation.xml'}
    if suffix in office_parts:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(x.file_size for x in z.infolist())>200*1024*1024 or len(z.infolist())>10000:
                    raise HTTPException(422, '压缩文档展开体积过大')
                if office_parts[suffix] not in z.namelist() or any('vbaproject' in x.lower() for x in z.namelist()):
                    raise HTTPException(422, '格式与扩展名不符或包含宏')
        except zipfile.BadZipFile:
            raise HTTPException(422, '损坏的 Office 文件')
    elif suffix=='.pdf' and not data.startswith(b'%PDF-'):
        raise HTTPException(422, '无效 PDF 文件')
    elif suffix in ('.doc','.xls') and not data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise HTTPException(422, '无效旧版 Office 文件')
    return name


def isolated_parse(file_hash: str, filename: str, *options: str) -> dict:
    command = [sys.executable,'-m','app.parse_worker',str(blob(file_hash).resolve()),Path(filename).suffix.lower()]
    command.extend(options)
    result = subprocess.run(command, capture_output=True, timeout=settings.parse_timeout, encoding='utf-8', env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or '文件解析失败')
    return json.loads(result.stdout)


class WordConversionError(RuntimeError):
    pass


def convert_word(path: Path, directory: Path) -> Path:
    source = directory/'input.doc'
    source.write_bytes(path.read_bytes())
    target = directory/'input.docx'
    executable=settings.converter_executable
    if executable=='word-com' and sys.platform=='win32':
        shell=which('pwsh.exe') or 'powershell.exe'
        command=[shell,'-NoProfile','-NonInteractive','-File',str(Path(__file__).parents[1]/'convert_doc.ps1'),str(source),str(target)]
    elif Path(executable).name.lower()=='wordconv.exe':
        command=[executable,'-oice','-nme',str(source),str(target)]
    else:
        command=[executable,'-env:UserInstallation=file:///'+(directory/'profile').as_posix(),'--headless','--convert-to','docx','--outdir',str(directory),str(source)]
    try:
        result=subprocess.run(command,capture_output=True,timeout=60,encoding='utf-8',errors='replace')
    except FileNotFoundError as error:
        raise WordConversionError('找不到 DOC 转换程序，请联系管理员检查转换器配置。') from error
    except subprocess.TimeoutExpired as error:
        raise WordConversionError('DOC 转换超时，请用 Word 打开文件确认能够正常读取后再重试。') from error
    if result.returncode:
        diagnostic=(result.stderr+'\n'+result.stdout).lower()
        if any(code in diagnostic for code in ('pssecurityexception','securityerror','execution_policies')):
            raise WordConversionError('DOC 转换脚本被 Windows PowerShell 执行策略拦截。请联系管理员检查转换环境，或将原件另存为 DOCX 后上传。')
        if '80040154' in diagnostic or 'regdb_e_classnotreg' in diagnostic:
            raise WordConversionError('无法启动 Microsoft Word 转换 DOC。请联系管理员检查 Word 安装。')
        raise WordConversionError(f'DOC 转换失败（退出码 {result.returncode}）。请确认文件能在 Word 中打开，或另存为 DOCX 后上传。')
    if not target.is_file() or not zipfile.is_zipfile(target):
        raise WordConversionError('DOC 转换未生成有效的 DOCX，请检查原文件能否在 Word 中正常打开。')
    return target


def parse_file(path: Path, suffix: str) -> dict:
    blocks: list[dict] = []
    warnings: list[str] = []
    display=[]
    if suffix=='.doc':
        # Converter is configured by operator; no command is sourced from uploaded content.
        with tempfile.TemporaryDirectory() as directory:
            result=parse_file(convert_word(path,Path(directory)),'.docx')
            result['warnings'].append('DOC 已转换；复杂版式与图片需人工核对，原始文件保持不变')
            return result
    if suffix=='.docx':
        from docx import Document
        from docx.text.paragraph import Paragraph
        doc=Document(path)
        section='正文'
        table_index=0
        paragraph_index=0
        for element in doc.iter_inner_content():
            if isinstance(element,Paragraph):
                paragraph_index+=1
                text=element.text.strip()
                if not text:
                    continue
                if 'heading' in element.style.name.lower() or (len(text)<60 and re.match(r'^\d+(?:\.\d+)*[ .、]',text) and any(r.bold for r in element.runs)):
                    section=text
                blocks.append({'kind':'paragraph','locator':f'{section} / 段落{paragraph_index}','text':text})
                display.append(text)
            else:
                table_index+=1
                display.append('')
                for i,row in enumerate(element.rows,1):
                    display.append('| '+' | '.join(cell.text.strip().replace('|','\\|').replace('\n','<br>') for cell in row.cells)+' |')
                    if i==1:
                        display.append('| '+' | '.join('---' for _ in row.cells)+' |')
                    for j,cell in enumerate(row.cells,1):
                        if cell.text.strip():
                            blocks.append({'kind':'cell','locator':f'{section} / 表{table_index}/R{i}C{j}','text':cell.text.strip()})
                display.append('')
        if doc.inline_shapes:
            warnings.append(f'发现 {len(doc.inline_shapes)} 个内嵌图形，未进行 OCR，必须人工核对')
        warnings.append('段落及表格定位已保留；页码与自动编号需渲染原件核对')
    elif suffix=='.pdf':
        import pymupdf as fitz
        with fitz.open(path) as doc:
            for i,page in enumerate(doc,1):
                text=page.get_text()
                if text.strip():
                    blocks.append({'kind':'page','locator':f'第{i}页','text':text})
                else:
                    warnings.append(f'第{i}页无可提取文本，需要 OCR')
    elif suffix=='.pptx':
        blocks=presentation_blocks(path)
        warnings.append('按幻灯片顺序提取正文与表格文字，图片、图表数值和演讲者备注需要核对原件')
    elif suffix in ('.xlsx','.xls'):
        if suffix=='.xlsx':
            from openpyxl import load_workbook
            with path.open('rb') as stream:
                wb=load_workbook(stream,read_only=True,data_only=True,keep_links=False)
                try:
                    for sheet in wb.worksheets:
                        for i,row in enumerate(sheet.values,1):
                            append_sheet_row(blocks,sheet.title,i,row)
                finally:
                    wb.close()
        else:
            import xlrd
            wb=xlrd.open_workbook(file_contents=path.read_bytes())
            for sheet in wb.sheets():
                for i in range(sheet.nrows):
                    append_sheet_row(blocks,sheet.name,i+1,sheet.row_values(i))
        warnings.append('只读取公式缓存值，不执行公式；台账导入单独保留原始字段')
    else:
        raw=path.read_bytes()
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text=raw.decode('gb18030')
        if suffix=='.csv':
            for i,row in enumerate(csv.reader(io.StringIO(text)),1):
                blocks.append({'kind':'row','locator':f'第{i}行','text':' | '.join(row)})
        else:
            for i,line in enumerate(text.splitlines(),1):
                if line.strip():
                    blocks.append({'kind':'paragraph','locator':f'第{i}行','text':line})
    content='\n'.join(display) if suffix=='.docx' else '\n'.join(x['text'] for x in blocks)
    if not content.strip():
        raise RuntimeError('未解析到文本；请 OCR 或转换后重新上传')
    if len(content)>2000000 or len(blocks)>50000:
        raise RuntimeError('解析内容超出受控资源限制')
    return {'content':content,'blocks':blocks,'warnings':warnings}


def presentation_blocks(path: Path) -> list[dict]:
    p='{http://schemas.openxmlformats.org/presentationml/2006/main}'
    a='{http://schemas.openxmlformats.org/drawingml/2006/main}'
    relationships='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    blocks=[]
    with zipfile.ZipFile(path) as archive:
        def read_part(name):
            data=archive.read(name)
            if b'<!DOCTYPE' in data.upper():
                raise ValueError('不支持含文档类型声明的 PPTX 内容')
            return ET.fromstring(data)

        content=read_part('ppt/presentation.xml')
        paths={item.attrib['Id']:item.attrib['Target'] for item in read_part('ppt/_rels/presentation.xml.rels')
               if item.get('Type','').endswith('/slide') and item.get('TargetMode')!='External'}
        for index, slide in enumerate(content.findall(f'{p}sldIdLst/{p}sldId'), 1):
            target=paths[slide.attrib[relationships+'id']]
            entry=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('ppt',target))
            if not entry.startswith('ppt/slides/'):
                raise ValueError('PPTX 幻灯片路径无效')
            for number, paragraph in enumerate(read_part(entry).iter(a+'p'), 1):
                text=''.join(node.text or '' for node in paragraph.iter(a+'t')).strip()
                if text:
                    blocks.append({'kind':'paragraph','locator':f'第{index}张幻灯片 / 段落{number}','text':text})
    return blocks


def append_sheet_row(blocks, name, row_number, row):
    if row_number>50000:
        raise RuntimeError('工作表超过可索引行数限制')
    if not any(value is not None and value!='' for value in row):
        return
    text=' | '.join('' if value is None else str(value) for value in row)
    blocks.append({'kind':'row','locator':f'{name}!第{row_number}行','text':text})
    if len(blocks)>50000:
        raise RuntimeError('解析内容超出受控资源限制')


def text_blocks(content: str) -> list[dict]:
    return [{'kind':'paragraph','locator':f'编辑稿/第{i}行','text':t} for i,t in enumerate(content.splitlines(),1) if t.strip()]
