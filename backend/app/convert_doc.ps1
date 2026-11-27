param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference='Stop'
$wordConverter=$null
$convertedDocument=$null
$stage='start Word'
try {
    $wordConverter=New-Object -ComObject Word.Application
    $stage='configure Word'
    $wordConverter.Visible=$false
    $wordConverter.DisplayAlerts=0
    $wordConverter.AutomationSecurity=3
    $stage='open DOC'
    $convertedDocument=$wordConverter.Documents.Open($InputPath,$false,$true,$false)
    $stage='save DOCX'
    $convertedDocument.SaveAs2($OutputPath,16)
} catch {
    throw "Word conversion could not $stage ($($_.Exception.HResult.ToString('X8'))): $($_.Exception.Message)"
} finally {
    if ($convertedDocument) {
        try { $convertedDocument.Close(0) } catch { Write-Warning 'Word did not respond while closing the converted file.' }
    }
    if ($wordConverter) {
        try { $wordConverter.Quit() } catch { Write-Warning 'Word did not respond while closing the conversion session.' }
    }
}
