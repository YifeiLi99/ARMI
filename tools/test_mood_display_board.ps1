[CmdletBinding()]
param(
    [string]$Port = 'COM3',
    [ValidateRange(0.1, 3600)][double]$Seconds = 4,
    [ValidateRange(0, 100)][int]$Energy = 70,
    [ValidateRange(1, 1000)][int]$Cycles = 1,
    [string[]]$Face,
    [switch]$Cyan
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '缺少项目 Python 环境，请先按项目说明准备依赖。'
}
$demoArguments = @('-X', 'utf8', '-m', 'tools.test_mood_display_board',
    '--port', $Port, '--seconds', $Seconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--energy', "$Energy", '--cycles', "$Cycles")
if ($Face) { $demoArguments += @('--face') + $Face }
if ($Cyan) { $demoArguments += '--cyan' }
Push-Location -LiteralPath $repositoryRoot
try {
    & $python @demoArguments
    if ($LASTEXITCODE -ne 0) { throw "实板演示失败，退出码：$LASTEXITCODE" }
}
finally { Pop-Location }
