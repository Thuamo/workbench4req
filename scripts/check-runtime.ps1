$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$env:PYTHONPATH=Join-Path $taskRoot 'backend'
$env:PYTHONIOENCODING='utf-8'
& scripts/start-local.ps1
if ($LASTEXITCODE -ne 0) { throw 'Startup failed' }
