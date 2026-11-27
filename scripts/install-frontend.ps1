$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
& npm.cmd install
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed' }
