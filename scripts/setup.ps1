$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$runtimePython = 'C:\Users\m1775\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { & $runtimePython -m venv .venv }
& '.venv\Scripts\python.exe' -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
& '.venv\Scripts\python.exe' -m pip freeze | Set-Content -Encoding utf8 backend/requirements.lock
