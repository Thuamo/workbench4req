from pathlib import Path
import zipfile, json, importlib.util, sys, shutil, argparse

ROOT = Path(__file__).resolve().parents[1]
print('Python:', sys.version)
print('Dependencies:', {m: bool(importlib.util.find_spec(m)) for m in ['fastapi','sqlalchemy','docx','openpyxl','fitz','pytest','langgraph','argon2','httpx','alembic','cryptography']})
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path)
args=parser.parse_args()
source = args.source or ROOT/'reference_files/文件包.zip'
if not source.exists() and args.source is None:
    source=Path(r'C:\Users\m1775\Downloads\文件包.zip')
target = ROOT / 'reference_files'
target.mkdir(exist_ok=True)
if source.resolve()!=(target/'文件包.zip').resolve():
    shutil.copyfile(source,target/'文件包.zip')
with zipfile.ZipFile(source) as archive:
    for item in archive.infolist():
        name = item.filename
        if not item.flag_bits & 0x800:
            try:
                name = name.encode('cp437').decode('gb18030')
            except (UnicodeError, LookupError):
                pass
        destination = (target / name).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ValueError('Unsafe archive path')
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(item))
        print(name, item.file_size, ascii(name))
report = []
for path in target.rglob('*'):
    if not path.is_file():
        continue
    if path.suffix.lower()=='.zip':
        continue
    record = {'path': str(path.relative_to(target)), 'bytes': path.stat().st_size}
    if path.suffix.lower() == '.docx':
        from docx import Document
        doc = Document(path)
        record.update(paragraphs=[{'style': p.style.name, 'text': p.text} for p in doc.paragraphs if p.text.strip()], tables=[[[c.text for c in row.cells] for row in t.rows] for t in doc.tables], sections=[{'top': s.top_margin.cm if s.top_margin else None,'bottom': s.bottom_margin.cm if s.bottom_margin else None,'left': s.left_margin.cm if s.left_margin else None,'right': s.right_margin.cm if s.right_margin else None,'header': [p.text for p in s.header.paragraphs], 'footer': [p.text for p in s.footer.paragraphs]} for s in doc.sections])
    elif path.suffix.lower() == '.xlsx':
        from openpyxl import load_workbook
        wb=load_workbook(path, data_only=True)
        record['sheets'] = [{'name':s.title,'rows':s.max_row,'columns':s.max_column,'merged':list(map(str,s.merged_cells.ranges)), 'data':list(s.values)} for s in wb]
    report.append(record)
(ROOT / 'docs').mkdir(exist_ok=True)
(ROOT / 'docs' / 'reference-extraction.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
for r in report:
    print(json.dumps({k:v for k,v in r.items() if k not in ('paragraphs','tables')},ensure_ascii=False,default=str)[:5000])
    if 'paragraphs' in r:
        print('HEADINGS:', [p for p in r['paragraphs'] if 'heading' in p['style'].lower() or len(p['text'])<70][:80])
        print('TABLES:', str(r['tables'])[:1500])
