$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& '.venv\Scripts\python.exe' -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependencies failed' }
& '.venv\Scripts\python.exe' -m pip freeze | Set-Content -Encoding utf8 backend/requirements.lock
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH=Join-Path $taskRoot 'backend'
$env:DATABASE_URL='sqlite:///./data/workbench.db'
& '.venv\Scripts\python.exe' -m compileall -q backend/app
if ($LASTEXITCODE -ne 0) { throw 'Compile failed' }
Set-Location -LiteralPath (Join-Path $taskRoot 'backend')
$env:DATABASE_URL='sqlite:///../data/workbench.db'
& '..\.venv\Scripts\python.exe' -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
& '..\.venv\Scripts\python.exe' -m app.cli seed
if ($LASTEXITCODE -ne 0) { throw 'Seed failed' }
Set-Location -LiteralPath $taskRoot
& '.venv\Scripts\python.exe' -m pytest backend/tests -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
