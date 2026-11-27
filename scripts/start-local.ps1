$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup.ps1 first' }
if (-not (Test-Path -LiteralPath 'frontend\.next\standalone\server.js')) { throw 'Build the frontend with scripts/check-frontend.ps1 first' }
$nodeExecutable=(Get-Command node.exe -ErrorAction Stop).Source
foreach ($taskPort in @(8000,3000)) {
    if (Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue) { throw "Port $taskPort is in use; stop the managed services before starting" }
}
if (-not (Test-Path -LiteralPath '.env')) {
    $taskKey= & $taskPython -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    $taskEnvLines=@('DATABASE_URL=sqlite:///./data/workbench-v1.db','STORAGE_DIR=./data','PUBLIC_ORIGIN=http://localhost:3000','COOKIE_SECURE=false',"ENCRYPTION_KEY=$taskKey",'CONVERTER_EXECUTABLE=word-com')
    [System.IO.File]::WriteAllLines((Join-Path $taskRoot '.env'),$taskEnvLines,(New-Object System.Text.UTF8Encoding($false)))
}
$env:PYTHONPATH=Join-Path $taskRoot 'backend'
$env:PYTHONIOENCODING='utf-8'
$env:NEXT_TELEMETRY_DISABLED='1'
# Migrations run from the same cwd/env as API and Worker.
& $taskPython -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
& $taskPython -m app.cli seed
if ($LASTEXITCODE -ne 0) { throw 'Seed failed' }
New-Item -ItemType Directory -Force -Path 'data' | Out-Null
$taskProcesses=@{}
if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    $apiProcess=Start-Process -FilePath $taskPython -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data\api.log') -RedirectStandardError (Join-Path $taskRoot 'data\api-error.log')
    $taskProcesses.api=$apiProcess.Id
} else { throw 'Port 8000 is already in use; inspect before starting another API' }
$workerProcess=Start-Process -FilePath $taskPython -ArgumentList '-m','app.worker' -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data\worker.log') -RedirectStandardError (Join-Path $taskRoot 'data\worker-error.log')
$taskProcesses.worker=$workerProcess.Id
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
    $env:HOSTNAME='127.0.0.1'
    $env:PORT='3000'
    $webProcess=Start-Process -FilePath $nodeExecutable -ArgumentList '.next\standalone\server.js' -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data\web.log') -RedirectStandardError (Join-Path $taskRoot 'data\web-error.log')
    $taskProcesses.web=$webProcess.Id
} else { throw 'Port 3000 is already in use; inspect before starting another web service' }
$taskProcesses | ConvertTo-Json | Set-Content -LiteralPath 'data\local-processes.json' -Encoding utf8
Write-Output 'Workbench starting at http://localhost:3000; logs are in data/.'
