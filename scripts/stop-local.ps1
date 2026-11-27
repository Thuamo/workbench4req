$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPidFile=Join-Path $taskRoot 'data\local-processes.json'
if (-not (Test-Path -LiteralPath $taskPidFile)) { throw 'No managed local process record exists' }
$taskRecords=Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
foreach ($taskService in @('api','worker','web')) {
    $taskProcessId=$taskRecords.$taskService
    if (-not $taskProcessId) { continue }
    $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
    if (-not $taskProcess) { continue }
    $taskExpected=switch ($taskService) { 'api' { 'app.main:app' } 'worker' { 'app.worker' } 'web' { 'standalone[\\/]server\.js|next.*start' } }
    if ($taskProcess.CommandLine -notmatch $taskExpected) { throw "Process ownership check failed for $taskService ($taskProcessId)" }
    if ($taskService -ne 'web' -and $taskProcess.ExecutablePath -ne (Join-Path $taskRoot '.venv\Scripts\python.exe')) { throw "Unexpected executable for $taskService" }
    Stop-Process -Id $taskProcessId
    Write-Output "Stopped managed $taskService process $taskProcessId"
}
