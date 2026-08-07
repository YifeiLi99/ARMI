[CmdletBinding()]
param(
    [ValidateSet('Start', 'Stop', 'Status')]
    [string]$Action = 'Start'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $workspace 'compose.yaml'
$stateRoot = Join-Path $workspace '.tmp/docker-postgresql'
$environmentFile = Join-Path $stateRoot 'compose.env'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'PG-DOCKER-CLI: Docker CLI is unavailable'
}

& docker info --format '{{.ServerVersion}}' 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PG-DOCKER-ENGINE: Docker Engine is unavailable'
}

if ($Action -eq 'Start' -and -not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $passwordBytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $password = [Convert]::ToHexString($passwordBytes).ToLowerInvariant()
    $content = @(
        'ARMI_POSTGRES_DATABASE=armi'
        'ARMI_POSTGRES_BOOTSTRAP_USER=armi_bootstrap'
        "ARMI_POSTGRES_BOOTSTRAP_PASSWORD=$password"
        'ARMI_POSTGRES_PORT=5432'
    ) -join "`n"
    [IO.File]::WriteAllText($environmentFile, "$content`n", [Text.UTF8Encoding]::new($false))
}

if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw 'PG-DOCKER-CONFIG: start PostgreSQL once before using stop or status'
}

$compose = @(
    'compose'
    '--env-file', $environmentFile
    '--file', $composeFile
)

switch ($Action) {
    'Start' {
        & docker @compose up --detach --wait postgresql
    }
    'Stop' {
        & docker @compose stop postgresql
    }
    'Status' {
        & docker @compose ps postgresql
    }
}
if ($LASTEXITCODE -ne 0) {
    throw "PG-DOCKER-$($Action.ToUpperInvariant()): Docker Compose failed"
}

if ($Action -eq 'Start') {
    [pscustomobject]@{
        status = 'ready'
        host = '127.0.0.1'
        port = 5432
        database = 'armi'
        bootstrap_user = 'armi_bootstrap'
        credential_file = $environmentFile
    }
}
