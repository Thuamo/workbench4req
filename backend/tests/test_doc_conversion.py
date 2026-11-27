from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.services import files


def test_word_com_uses_available_powershell_7(tmp_path, monkeypatch):
    source = tmp_path/'original.doc'
    source.write_bytes(b'legacy word file')
    work = tmp_path/'convert'
    work.mkdir()
    monkeypatch.setattr(files.settings, 'converter_executable', 'word-com')
    monkeypatch.setattr(files, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(files, 'which', lambda name: '/installed/pwsh.exe')

    def run(command, **kwargs):
        assert command[:5] == ['/installed/pwsh.exe', '-NoProfile', '-NonInteractive', '-File',
                               str(files.Path(files.__file__).parents[1]/'convert_doc.ps1')]
        assert files.Path(command[-2]).read_bytes() == source.read_bytes()
        with ZipFile(command[-1], 'w') as converted:
            converted.writestr('word/document.xml', '<document/>')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(files.subprocess, 'run', run)
    assert files.convert_word(source, work) == work/'input.docx'


def test_word_com_reports_script_execution_policy(tmp_path, monkeypatch):
    source = tmp_path/'original.doc'
    source.touch()
    monkeypatch.setattr(files.settings, 'converter_executable', 'word-com')
    monkeypatch.setattr(files, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(files, 'which', lambda name: None)

    def run(command, **kwargs):
        assert command[0] == 'powershell.exe'
        return SimpleNamespace(returncode=1, stdout='', stderr='PSSecurityException: running scripts is disabled')

    monkeypatch.setattr(files.subprocess, 'run', run)
    with pytest.raises(files.WordConversionError, match='执行策略拦截'):
        files.convert_word(source, tmp_path)
