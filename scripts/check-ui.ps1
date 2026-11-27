$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& 'C:\Users\m1775\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts/ui-smoke.mjs
if ($LASTEXITCODE -ne 0) { throw 'UI smoke test failed' }
