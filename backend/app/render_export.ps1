param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference='Stop'
$taskWord=New-Object -ComObject Word.Application
$taskDocument=$null
try {
    $taskWord.Visible=$false
    $taskWord.DisplayAlerts=0
    $taskWord.AutomationSecurity=3
    $taskDocument=$taskWord.Documents.Open($InputPath,$false,$true,$false)
    $taskDocument.Repaginate()
    $taskDocument.ExportAsFixedFormat($OutputPath,17)
} finally {
    if ($null -ne $taskDocument) { try { $taskDocument.Close(0) } catch { Write-Verbose 'Word already closed the rendered document' } }
    try { $taskWord.Quit() } catch { Write-Verbose 'Word already exited after rendering' }
}
