from pathlib import Path
import pymupdf as fitz, json
root=Path(__file__).resolve().parents[1]/'test-results/word-render'
manifest=[]
for pdf in root.glob('*.pdf'):
    directory=root/pdf.stem
    directory.mkdir(exist_ok=True)
    with fitz.open(pdf) as doc:
        pages=[]
        for index,page in enumerate(doc,1):
            png=directory/f'page-{index:02}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(png)
            pages.append({'path':str(png),'text_length':len(page.get_text()),'page':index})
        manifest.append({'file':pdf.name,'pages':pages})
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'documents':len(manifest),'pages':sum(len(x['pages']) for x in manifest)},ensure_ascii=False))
