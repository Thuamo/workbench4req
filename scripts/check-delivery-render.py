"""Synthetic export fixture only; no business documents and no model calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from app.services.delivery import SRS_TEMPLATE
from app.services.export import export_docx
from app.services.export_preview import render

root=Path(__file__).resolve().parents[1]/'test-results'/'delivery-render'
root.mkdir(parents=True,exist_ok=True)
lines=['# 1 需求背景与目标','本文件仅用于验证排版，不包含真实业务资料。','## 1.1 目标','- 保留**业务规则**与*人工确认*的格式。','- 页面、表格和分页可人工核对。','# 2 核心功能需求']
for i in range(1,8):
    lines += [f'## 2.{i} 测试功能', '系统在测试业务提交时检查输入字段；未知规则标为待确认。'*4,
              '| 字段 | 处理规则 | 异常说明 |','| --- | --- | --- |',
              '| 测试状态 | 保留原始值与处理记录，不推定未知业务口径 | 缺少依据时标记为待确认 |',
              '| 测试编号 | 按所选业务需求、系统与项目关联，保留所有原表行 | 同编号不同业务需人工核对 |']
version=SimpleNamespace(id='render-fixture',label='V1.0',publish_status='draft',change_note='合成数据排版回归',warnings=[],content='\n'.join(lines),provenance={'delivery_template':SRS_TEMPLATE})
docx=export_docx(SimpleNamespace(title='软件需求说明书 · 排版验证'),version)
(root/'requirements.docx').write_bytes(docx)
pdf,report=render(docx);(root/'requirements.pdf').write_bytes(pdf)
import fitz
with fitz.open(stream=pdf,filetype='pdf') as document:
    for index,page in enumerate(document):page.get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(root/f'page-{index+1}.png')
(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert report['pages']>=2,report
assert not report['warnings'],report
print(json.dumps(report,ensure_ascii=False))
