$ErrorActionPreference='Stop'
Push-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
try {
    $env:NEXT_TELEMETRY_DISABLED='1'
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Typecheck failed' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally {
    Pop-Location
}
