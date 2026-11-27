$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$env:PYTHONPATH=Join-Path $taskRoot 'backend'
& '.venv\Scripts\python.exe' scripts/verify-migrations.py
if ($LASTEXITCODE -ne 0) { throw 'Migration verification failed' }
& '.venv\Scripts\python.exe' scripts/export-openapi.py
if ($LASTEXITCODE -ne 0) { throw 'OpenAPI export failed' }
$taskHealth=Invoke-RestMethod 'http://127.0.0.1:8000/health'
if ($taskHealth.status -ne 'ok') { throw 'API health failed' }
$taskWeb=Invoke-WebRequest 'http://localhost:3000' -UseBasicParsing
if ($taskWeb.StatusCode -ne 200) { throw 'Web health failed' }
Write-Output 'API health, Web response, migration head, immutable constraints and OpenAPI verified'
