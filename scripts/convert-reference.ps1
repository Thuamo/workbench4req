$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$source=Get-ChildItem -LiteralPath 'reference_files\文件包' -Filter '*.doc' | Select-Object -First 1
$target=Join-Path $source.DirectoryName ($source.BaseName+'.converted.docx')
& 'C:\Program Files (x86)\Microsoft Office\root\Office16\Wordconv.exe' -oice -nme $source.FullName $target
if (-not (Test-Path -LiteralPath $target)) {
    Write-Output "Wordconv exit code: $LASTEXITCODE; trying read-only Word COM conversion"
    $wordConverter=New-Object -ComObject Word.Application
    try {
        $wordConverter.Visible=$false
        $wordConverter.DisplayAlerts=0
        $wordConverter.AutomationSecurity=3
        $convertedDocument=$wordConverter.Documents.Open($source.FullName,$false,$true,$false)
        $convertedDocument.SaveAs2($target,16)
        $convertedDocument.Close(0)
    } finally { $wordConverter.Quit() }
}
if (-not (Test-Path -LiteralPath $target)) { throw 'DOC conversion failed' }
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\m1775\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts/inspect_references.py
