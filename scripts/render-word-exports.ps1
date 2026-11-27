$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskInput=Join-Path $taskRoot 'test-results\word-exports'
$taskOutput=Join-Path $taskRoot 'test-results\word-render'
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
foreach ($taskFile in (Get-ChildItem -LiteralPath $taskInput -Filter '*.docx')) {
    $taskWord=New-Object -ComObject Word.Application
    try {
    $taskWord.Visible=$false
    $taskWord.DisplayAlerts=0
    $taskWord.AutomationSecurity=3
        $taskPdf=Join-Path $taskOutput ($taskFile.BaseName+'.pdf')
        $taskDoc=$taskWord.Documents.Open($taskFile.FullName,$false,$true,$false)
        try { $taskDoc.ExportAsFixedFormat($taskPdf,17) } finally { $taskDoc.Close(0) }
        Write-Output "Rendered $($taskFile.Name)"
    } finally { try { $taskWord.Quit() } catch { Write-Verbose 'Word already exited after export' } }
}
$env:PYTHONPATH=Join-Path $taskRoot '.venv\Lib\site-packages'
& 'C:\Users\m1775\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' (Join-Path $PSScriptRoot 'render-word-pages.py')
if ($LASTEXITCODE -ne 0) { throw 'Word PNG rendering failed' }
