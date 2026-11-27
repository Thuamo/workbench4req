"""Render an authorized export for human page inspection, without a DB write lock."""
import os,subprocess,tempfile,threading
from pathlib import Path
from fastapi import HTTPException
from ..config import settings

_render_lock=threading.Lock()

def render(data):
    if not _render_lock.acquire(blocking=False):raise HTTPException(409,'另一份文档正在生成排版预览，请稍后重试')
    try:
        with tempfile.TemporaryDirectory(prefix='srs-preview-') as directory:
            root=Path(directory);source=root/'document.docx';target=root/'document.pdf';source.write_bytes(data)
            if os.name=='nt' and settings.converter_executable=='word-com':
                command=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).parents[1]/'render_export.ps1'),str(source),str(target)]
            else:
                command=[settings.converter_executable,'-env:UserInstallation='+ (root/'profile').as_uri(),'--headless','--convert-to','pdf','--outdir',str(root),str(source)]
            try:
                subprocess.run(command,check=True,capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                result=target.read_bytes()
            except (OSError,subprocess.SubprocessError):raise HTTPException(424,'排版预览失败，请检查本地 Word / LibreOffice 转换配置；仍可下载 Word 文件核对')
            import fitz
            with fitz.open(stream=result,filetype='pdf') as pdf:
                if not len(pdf):raise HTTPException(424,'转换未产生有效页面')
                warnings=[]
                for page in pdf:
                    if not page.get_text().strip():warnings.append(f'第{page.number+1}页没有可提取文字，请人工核对')
                    if any(not page.rect.contains(fitz.Rect(word[:4])) for word in page.get_text('words')):warnings.append(f'第{page.number+1}页可能有超出纸张的文字')
                return result,{'pages':len(pdf),'warnings':warnings,'notice':'已实际渲染；业务内容、分页和表格仍需人工核对。'}
    finally:_render_lock.release()
