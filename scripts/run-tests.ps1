$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH=Join-Path $taskRoot 'backend'
& '.venv\Scripts\python.exe' -m pytest backend/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
