[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previewScript = Join-Path $PSScriptRoot 'mood_display_preview.py'
$pythonWindowed = Join-Path $repositoryRoot '.venv\Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $previewScript -PathType Leaf)) {
    throw "Mood display preview is missing: $previewScript"
}
if (-not (Test-Path -LiteralPath $pythonWindowed -PathType Leaf)) {
    throw 'Workspace Python is missing. Run uv sync --frozen first.'
}

Start-Process -FilePath $pythonWindowed -ArgumentList @($previewScript) -WorkingDirectory $repositoryRoot
