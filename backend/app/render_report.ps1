param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

$ErrorActionPreference='Stop'
$running=Get-Process POWERPNT -ErrorAction SilentlyContinue
$powerPoint=$null
$deck=$null
try {
    $powerPoint=New-Object -ComObject PowerPoint.Application
    $deck=$powerPoint.Presentations.Open($InputPath,-1,0,0)
    $width=1600
    $height=[int][Math]::Round($width*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
    $deck.Slides.Item(1).Export($OutputPath,'PNG',$width,$height)
} finally {
    if ($deck) {
        try { $deck.Close() } catch { Write-Warning 'PowerPoint did not respond while closing the preview deck.' }
    }
    if ($powerPoint -and -not $running) {
        try {
            if ($powerPoint.Presentations.Count -eq 0) { $powerPoint.Quit() }
        } catch { Write-Warning 'PowerPoint did not respond while closing the preview session.' }
    }
}
