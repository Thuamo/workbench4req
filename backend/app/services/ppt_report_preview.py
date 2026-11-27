import logging
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import pymupdf
from fastapi import HTTPException

from ..config import settings

_render_lock = Lock()
_png_header = b'\x89PNG\r\n\x1a\n'


def _export_first_slide(source: Path, target: Path):
    executable = settings.converter_executable
    native = os.name=='nt' and (executable=='word-com' or Path(executable).name.lower()=='wordconv.exe')
    if native:
        shell = shutil.which('pwsh.exe') or 'powershell.exe'
        script = Path(__file__).parents[1]/'render_report.ps1'
        command = [shell, '-NoProfile', '-NonInteractive', '-File', str(script), str(source), str(target)]
    else:
        profile = (source.parent/'profile').as_uri()
        command = [executable, '-env:UserInstallation='+profile, '--headless', '--convert-to', 'pdf:impress_pdf_Export',
                   '--outdir', str(source.parent), str(source)]
    subprocess.run(command, check=True, capture_output=True, timeout=45,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if not native:
        with pymupdf.open(source.with_suffix('.pdf')) as pdf:
            if not len(pdf):
                raise ValueError('PPT preview has no pages')
            page = pdf[0]
            scale = 1600/max(page.rect.width, page.rect.height)
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(target)


def report_preview(source: Path) -> Path:
    cache = settings.storage_dir/'previews'/'ppt-report'
    image = cache/(source.name+'.png')
    if image.is_file():
        return image
    if not _render_lock.acquire(timeout=20):
        raise HTTPException(503, 'PPT 预览正在排队，请稍后重试')
    try:
        if image.is_file():
            return image
        cache.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='render-', dir=cache.resolve()) as directory:
            input_file = Path(directory)/'report.pptx'
            output_file = Path(directory)/'preview.png'
            shutil.copyfile(source, input_file)
            _export_first_slide(input_file, output_file)
            with output_file.open('rb') as stream:
                if stream.read(8)!=_png_header:
                    raise ValueError('PPT preview did not produce a PNG')
            output_file.replace(image)
        return image
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        logging.warning('PPT preview conversion failed: %s', type(error).__name__)
        raise HTTPException(424, 'PPT 图片预览暂不可用，可下载 PPTX 查看') from error
    finally:
        _render_lock.release()
