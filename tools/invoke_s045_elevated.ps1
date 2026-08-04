[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RepositoryRoot,
    [Parameter(Mandatory)] [string]$EnvironmentRoot,
    [Parameter(Mandatory)] [string]$Installation,
    [Parameter(Mandatory)] [string]$IncompatibleInstallation,
    [Parameter(Mandatory)] [string]$SummaryPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $IsWindows -or $PSVersionTable.PSEdition -ne 'Core') {
    throw 'S045-WINDOWS-REQUIRED'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'S045-ELEVATION-REQUIRED'
}

$repo = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$environment = (Resolve-Path -LiteralPath $EnvironmentRoot).Path
$install = (Resolve-Path -LiteralPath $Installation).Path
$incompatible = (Resolve-Path -LiteralPath $IncompatibleInstallation).Path
$summary = [IO.Path]::GetFullPath($SummaryPath)
$deployment = Join-Path (Split-Path -Parent $environment) 'deployment'
if (-not $install.StartsWith((Join-Path $deployment 'installations'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'S045-INSTALL-BOUNDARY'
}

$suffix = [guid]::NewGuid().ToString('N').Substring(0, 6)
$names = [ordered]@{
    runtime = "armi45r$suffix"
    admin = "armi45a$suffix"
    migrator = "armi45m$suffix"
}
$credentials = @{}
$sids = @{}
$created = [Collections.Generic.List[string]]::new()
$runtimeStopped = $false
$activeCleared = $false
$accountsRemoved = $false
$bundleIdentity = Get-Content -LiteralPath (Join-Path $install 'bundle-identity.json') -Raw -Encoding utf8 -ErrorAction SilentlyContinue
if ([string]::IsNullOrEmpty($bundleIdentity)) {
    $bundleIdentity = Get-Content -LiteralPath (Join-Path $install 'bundle/bundle-identity.json') -Raw -Encoding utf8
}
$bundle = $bundleIdentity | ConvertFrom-Json -Depth 50
$bundleId = [string]$bundle.bundle_id
$scratch = Join-Path $environment 'run/s045'

function New-Password {
    return [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(36))
}

function Add-Rule {
    param(
        [Security.AccessControl.FileSystemSecurity]$Acl,
        [string]$Sid,
        [Security.AccessControl.FileSystemRights]$Rights,
        [Security.AccessControl.InheritanceFlags]$Inheritance = [Security.AccessControl.InheritanceFlags]::None
    )
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new($Sid),
        $Rights,
        $Inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    [void]$Acl.AddAccessRule($rule)
}

function Set-ProtectedAcl {
    param(
        [string]$Path,
        [hashtable]$Rules,
        [switch]$Directory
    )
    $acl = if ($Directory) {
        [Security.AccessControl.DirectorySecurity]::new()
    } else {
        [Security.AccessControl.FileSecurity]::new()
    }
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    } else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    Add-Rule $acl 'S-1-5-18' ([Security.AccessControl.FileSystemRights]::FullControl) $inheritance
    Add-Rule $acl 'S-1-5-32-544' ([Security.AccessControl.FileSystemRights]::FullControl) $inheritance
    foreach ($entry in $Rules.GetEnumerator()) {
        Add-Rule $acl ([string]$entry.Key) ([Security.AccessControl.FileSystemRights]$entry.Value) $inheritance
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Restore-CleanupAcl {
    param([string]$Path, [string]$OwnerSid)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $items = @(Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop)
    foreach ($item in @($items | Sort-Object { $_.FullName.Length })) {
        Set-ProtectedAcl $item.FullName @{
            $OwnerSid = [Security.AccessControl.FileSystemRights]::FullControl
        } -Directory:$item.PSIsContainer
    }
    Set-ProtectedAcl $Path @{
        $OwnerSid = [Security.AccessControl.FileSystemRights]::FullControl
    } -Directory
}

function Invoke-As {
    param(
        [string]$Role,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label,
        [hashtable]$ExtraEnvironment = @{}
    )
    $stdout = Join-Path $scratch "$Label.out"
    $stderr = Join-Path $scratch "$Label.err"
    $processEnvironment = @{
        PATH = (Join-Path $install 'venv/Scripts') + ';' + (Join-Path $env:WINDIR 'System32')
        SYSTEMROOT = $env:SYSTEMROOT
        WINDIR = $env:WINDIR
        TEMP = $scratch
        TMP = $scratch
    }
    foreach ($entry in $ExtraEnvironment.GetEnumerator()) {
        $processEnvironment[[string]$entry.Key] = [string]$entry.Value
    }
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -Credential $credentials[$Role] -WorkingDirectory $environment `
        -WindowStyle Hidden -Wait -PassThru -Environment $processEnvironment `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $errorText = if (Test-Path -LiteralPath $stderr) {
        Get-Content -LiteralPath $stderr -Raw -Encoding utf8
    } else { '' }
    if ($process.ExitCode -ne 0) {
        throw "S045-$($Label.ToUpperInvariant()): $errorText"
    }
    $outputText = if (Test-Path -LiteralPath $stdout) {
        Get-Content -LiteralPath $stdout -Raw -Encoding utf8
    } else { '' }
    return $outputText.Trim()
}

function Invoke-Deploy {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $output = Join-Path $scratch ('deploy-' + [guid]::NewGuid().ToString('N') + '.out')
    $errorOutput = "$output.err"
    $deployArguments = @('-B', (Join-Path $repo 'tools/deploy_candidate.py')) + $Arguments
    $process = Start-Process -FilePath (Join-Path $repo '.venv/Scripts/python.exe') `
        -ArgumentList $deployArguments `
        -WorkingDirectory $repo -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput $output -RedirectStandardError $errorOutput
    $stdout = if (Test-Path -LiteralPath $output) { Get-Content $output -Raw -Encoding utf8 } else { '' }
    $stderr = if (Test-Path -LiteralPath $errorOutput) { Get-Content $errorOutput -Raw -Encoding utf8 } else { '' }
    if ($process.ExitCode -ne 0 -and -not $AllowFailure) { throw "S045-DEPLOY: $stderr" }
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout.Trim(); Stderr = $stderr.Trim() }
}

try {
    foreach ($role in $names.Keys) {
        $password = New-Password
        $secure = ConvertTo-SecureString $password -AsPlainText -Force
        New-LocalUser -Name $names[$role] -Password $secure -AccountNeverExpires `
            -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
        [void]$created.Add($names[$role])
        $credentials[$role] = [Management.Automation.PSCredential]::new(
            ".\$($names[$role])", $secure
        )
        $sids[$role] = ([Security.Principal.NTAccount]::new($env:COMPUTERNAME, $names[$role])).Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        $password = $null
    }

    New-Item -ItemType Directory -Path $scratch -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $environment 'run') -Force | Out-Null
    Set-ProtectedAcl $install @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.admin = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.migrator = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory
    Set-ProtectedAcl $environment @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.admin = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.migrator = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory
    Set-ProtectedAcl (Join-Path $environment 'data') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::Modify
        $sids.admin = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory
    Set-ProtectedAcl (Join-Path $environment 'run') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::Modify
        $sids.admin = [Security.AccessControl.FileSystemRights]::Modify
        $sids.migrator = [Security.AccessControl.FileSystemRights]::Modify
    } -Directory
    Set-ProtectedAcl (Join-Path $environment 'bootstrap') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory
    Set-ProtectedAcl (Join-Path $environment 'secrets') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.admin = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.migrator = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory
    foreach ($entry in @(
        @('runtime', $sids.runtime),
        @('creator', $sids.runtime),
        @('admin', $sids.admin),
        @('preview', $sids.admin),
        @('migrator', $sids.migrator)
    )) {
        Set-ProtectedAcl (Join-Path $environment "secrets/$($entry[0])") @{
            ([string]$entry[1]) = [Security.AccessControl.FileSystemRights]::Read
        }
    }
    Set-ProtectedAcl (Join-Path $environment 'environment.toml') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::Read
        $sids.admin = [Security.AccessControl.FileSystemRights]::Read
        $sids.migrator = [Security.AccessControl.FileSystemRights]::Read
    }
    Set-ProtectedAcl (Join-Path $environment 'admin.toml') @{
        $sids.admin = [Security.AccessControl.FileSystemRights]::Read
    }
    Set-ProtectedAcl (Join-Path $environment 'bootstrap/birth-manifest.json') @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::Read
    }
    Set-ProtectedAcl $deployment @{
        $sids.runtime = [Security.AccessControl.FileSystemRights]::ReadAndExecute
        $sids.admin = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    } -Directory

    $probeResults = [Collections.Generic.List[object]]::new()
    $probeSpecs = @{
        runtime = @{
            readable = @((Join-Path $environment 'secrets/runtime'), (Join-Path $environment 'secrets/creator'))
            forbidden = @((Join-Path $environment 'secrets/admin'), (Join-Path $environment 'secrets/migrator'))
            writable = (Join-Path $environment 'data')
        }
        admin = @{
            readable = @((Join-Path $environment 'secrets/admin'), (Join-Path $environment 'secrets/preview'))
            forbidden = @((Join-Path $environment 'secrets/runtime'), (Join-Path $environment 'secrets/migrator'))
            writable = (Join-Path $environment 'run')
        }
        migrator = @{
            readable = @((Join-Path $environment 'secrets/migrator'))
            forbidden = @((Join-Path $environment 'secrets/runtime'), (Join-Path $environment 'secrets/admin'))
            writable = (Join-Path $environment 'run')
        }
    }
    foreach ($role in $names.Keys) {
        $resultPath = Join-Path $scratch "$role-acl.json"
        $spec = $probeSpecs[$role]
        $arguments = @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            (Join-Path $repo 'tools/s045_acl_probe.ps1'),
            '-Readable'
        ) + @($spec.readable) + @('-Forbidden') + @($spec.forbidden) + @(
            '-WritableDirectory', $spec.writable,
            '-ResultPath', $resultPath
        )
        [void](Invoke-As $role 'pwsh' $arguments "$role-acl")
        $probe = Get-Content -LiteralPath $resultPath -Raw -Encoding utf8 | ConvertFrom-Json
        if ($probe.sid -ne $sids[$role] -or $probe.passed -ne $true) { throw 'S045-ACL-PROBE' }
        [void]$probeResults.Add([ordered]@{ role = $role; sid = $probe.sid; passed = $true })
    }

    [void](Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'config', 'check', '--environment-root', $environment
    ) 'runtime-config')
    [void](Invoke-As 'migrator' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'db', 'upgrade', '--environment-root', $environment
    ) 'schema-upgrade')
    $schemaStatus = Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'db', 'status', '--environment-root', $environment
    ) 'schema-status' | ConvertFrom-Json
    if ($schemaStatus.status -ne 'current' -or $schemaStatus.current_version -ne 27) {
        throw 'S045-SCHEMA-STATUS'
    }
    $birth = Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'bootstrap', 'birth', '--environment-root', $environment
    ) 'birth' | ConvertFrom-Json
    if ($birth.status -notin @('applied', 'already_applied')) { throw 'S045-BIRTH' }
    $adminSmoke = Invoke-As 'admin' (Join-Path $install 'venv/Scripts/python.exe') @(
        '-I', (Join-Path $repo 'tools/s045_installed_probe.py'),
        'admin-smoke', '--environment-root', $environment
    ) 'admin-smoke' | ConvertFrom-Json

    $before = Invoke-As 'admin' (Join-Path $install 'venv/Scripts/python.exe') @(
        '-I', (Join-Path $repo 'tools/s045_installed_probe.py'),
        'snapshot', '--conninfo-file', (Join-Path $environment 'secrets/admin')
    ) 'snapshot-before' | ConvertFrom-Json

    $staged = Invoke-Deploy @('stage', '--installation', $install, '--environment-root', $environment, '--expected-active', 'none')
    $pending = $staged.Stdout | ConvertFrom-Json
    $started = Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'start', '--environment-root', $environment
    ) 'runtime-start' | ConvertFrom-Json
    $committed = Invoke-Deploy @('commit', '--activation-id', $pending.activation_id, '--runtime-sid', $sids.runtime)
    $active = $committed.Stdout | ConvertFrom-Json
    $creator = & (Join-Path $install 'venv/Scripts/python.exe') -I `
        (Join-Path $repo 'tools/s045_installed_probe.py') creator-input `
        --environment-root $environment | ConvertFrom-Json
    Start-Sleep -Milliseconds 500
    $withInput = Invoke-As 'admin' (Join-Path $install 'venv/Scripts/python.exe') @(
        '-I', (Join-Path $repo 'tools/s045_installed_probe.py'),
        'snapshot', '--conninfo-file', (Join-Path $environment 'secrets/admin')
    ) 'snapshot-input' | ConvertFrom-Json
    [void](Invoke-As 'admin' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'stop', '--environment-root', $environment
    ) 'runtime-stop')
    $runtimeStopped = $true
    $restarted = Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'start', '--environment-root', $environment
    ) 'runtime-restart' | ConvertFrom-Json
    $afterRestart = Invoke-As 'admin' (Join-Path $install 'venv/Scripts/python.exe') @(
        '-I', (Join-Path $repo 'tools/s045_installed_probe.py'),
        'snapshot', '--conninfo-file', (Join-Path $environment 'secrets/admin')
    ) 'snapshot-restart' | ConvertFrom-Json
    if ($withInput.facts_sha256 -ne $afterRestart.facts_sha256) { throw 'S045-FACTS-RESTART' }
    if ($afterRestart.latest_recovery[0] -ne 'safe') { throw 'S045-RECOVERY' }
    [void](Invoke-As 'admin' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'stop', '--environment-root', $environment
    ) 'runtime-stop-rollback')
    [void](Invoke-Deploy @('deactivate', '--environment-root', $environment, '--expected-active', $bundleId))
    $activeCleared = $true
    $afterRollback = Invoke-As 'admin' (Join-Path $install 'venv/Scripts/python.exe') @(
        '-I', (Join-Path $repo 'tools/s045_installed_probe.py'),
        'snapshot', '--conninfo-file', (Join-Path $environment 'secrets/admin')
    ) 'snapshot-rollback' | ConvertFrom-Json
    if ($afterRestart.facts_sha256 -ne $afterRollback.facts_sha256) { throw 'S045-FACTS-ROLLBACK' }

    $restaged = Invoke-Deploy @('stage', '--installation', $install, '--environment-root', $environment, '--expected-active', 'none')
    $repending = $restaged.Stdout | ConvertFrom-Json
    [void](Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'start', '--environment-root', $environment
    ) 'runtime-reactivate')
    [void](Invoke-Deploy @('commit', '--activation-id', $repending.activation_id, '--runtime-sid', $sids.runtime))
    $duplicate = Invoke-As 'runtime' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'start', '--environment-root', $environment
    ) 'runtime-duplicate' | ConvertFrom-Json
    if ($duplicate.status -ne 'already_running' -or $duplicate.pid -ne $active.pid) {
        throw 'S045-SINGLE-ACTIVE'
    }
    $incompatibleResult = Invoke-Deploy @(
        'stage', '--installation', $incompatible, '--environment-root', $environment,
        '--expected-active', $bundleId
    ) -AllowFailure
    if ($incompatibleResult.ExitCode -eq 0 -or $incompatibleResult.Stderr -notlike 'DEP-COMPATIBILITY-UNPROVEN*') {
        throw 'S045-INCOMPATIBLE-ACCEPTED'
    }
    [void](Invoke-As 'admin' (Join-Path $install 'venv/Scripts/armi.exe') @(
        'stop', '--environment-root', $environment
    ) 'runtime-final-stop')
    $runtimeStopped = $true
    [void](Invoke-Deploy @('deactivate', '--environment-root', $environment, '--expected-active', $bundleId))
    $activeCleared = $true

    $descriptors = foreach ($entry in @(
        @('database.runtime', 'runtime', $sids.runtime),
        @('creator.bearer', 'creator', $sids.runtime),
        @('database.admin', 'admin', $sids.admin),
        @('admin.preview', 'preview', $sids.admin),
        @('database.migrator', 'migrator', $sids.migrator)
    )) {
        [ordered]@{
            credential_class = $entry[0]
            reader_sid = $entry[2]
            sddl = (Get-Acl -LiteralPath (Join-Path $environment "secrets/$($entry[1])")).Sddl
        }
    }
    $activationRecord = [ordered]@{
        schema_version = 'armi.windows-credential-acl-activation.v1'
        active = $true
        descriptors = @($descriptors)
        access_matrix = @($probeResults)
        process_tokens = @([ordered]@{ role = 'runtime'; sid = $sids.runtime; passed = $true })
    }
    $activationPath = Join-Path $scratch 'acl-activation.json'
    [IO.File]::WriteAllText(
        $activationPath,
        (($activationRecord | ConvertTo-Json -Depth 20 -Compress) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    & pwsh -NoLogo -NoProfile -NonInteractive -File `
        (Join-Path $repo 'tools/check_windows_credential_acl.ps1') `
        -ActivationRecord $activationPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'S045-ACL-ACTIVATION' }

    $result = [ordered]@{
        status = 'pass'
        schema_version = 'armi.s045-elevated-summary.v1'
        service_identity_mode = 'temporary_local_accounts'
        windows_sids = [ordered]@{
            runtime = $sids.runtime
            admin = $sids.admin
            migrator = $sids.migrator
        }
        acl = [ordered]@{ status = 'pass'; probe_count = $probeResults.Count }
        schema = [ordered]@{
            status = $schemaStatus.status
            target_version = $schemaStatus.target_version
            migration_set_sha256 = $schemaStatus.migration_set_sha256
        }
        admin_mcp = $adminSmoke
        activation = [ordered]@{
            initial_generation = $active.generation
            reactivation = 'pass'
            single_active = 'pass'
            incompatible_rejection = 'DEP-COMPATIBILITY-UNPROVEN'
        }
        recovery = [ordered]@{
            status = $afterRestart.latest_recovery[0]
            facts_before_restart = $withInput.facts_sha256
            facts_after_restart = $afterRestart.facts_sha256
            facts_after_rollback = $afterRollback.facts_sha256
            creator_input = $creator.status
        }
        cleanup = [ordered]@{
            runtime_stopped = $runtimeStopped
            active_cleared = $activeCleared
            accounts_removed = $false
        }
    }
} finally {
    try {
        if (Test-Path -LiteralPath (Join-Path $environment 'environment.toml')) {
            $stop = Start-Process -FilePath (Join-Path $install 'venv/Scripts/armi.exe') `
                -ArgumentList @('stop', '--environment-root', $environment) `
                -WorkingDirectory $environment -WindowStyle Hidden -Wait -PassThru
            $runtimeStopped = $stop.ExitCode -eq 0
        }
    } catch {
        $runtimeStopped = $false
    }
    try {
        $deploymentStatus = Invoke-Deploy @('status', '--environment-root', $environment)
        $deploymentState = $deploymentStatus.Stdout | ConvertFrom-Json
        if ($null -ne $deploymentState.active) {
            [void](Invoke-Deploy @(
                'deactivate', '--environment-root', $environment,
                '--expected-active', [string]$deploymentState.active.bundle_id
            ))
        }
        $deploymentStatus = Invoke-Deploy @('status', '--environment-root', $environment)
        $deploymentState = $deploymentStatus.Stdout | ConvertFrom-Json
        $activeCleared = $null -eq $deploymentState.active
    } catch {
        $activeCleared = $false
    }
    Restore-CleanupAcl $environment $identity.User.Value
    Restore-CleanupAcl $deployment $identity.User.Value
    foreach ($name in @($created)) {
        $account = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $account) {
            Remove-LocalUser -Name $name -ErrorAction Stop
        }
    }
    $accountsRemoved = @($created | Where-Object { $null -ne (Get-LocalUser -Name $_ -ErrorAction SilentlyContinue) }).Count -eq 0
}

if ($null -eq $result) { throw 'S045-NO-RESULT' }
$result.cleanup.accounts_removed = $accountsRemoved
if (-not $runtimeStopped -or -not $activeCleared -or -not $accountsRemoved) {
    throw 'S045-CLEANUP'
}
[IO.File]::WriteAllText(
    $summary,
    (($result | ConvertTo-Json -Depth 30) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
