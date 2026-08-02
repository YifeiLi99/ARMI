[CmdletBinding()]
param(
    [Parameter()]
    [string]$PolicyPath = "tools/windows-credential-acl-policy.json",

    [Parameter()]
    [string]$Sddl,

    [Parameter()]
    [string]$ExpectedReaderSid
)

$ErrorActionPreference = "Stop"

function Fail-AclPolicy {
    param([string]$Code, [string]$Message)
    [Console]::Error.WriteLine("$Code`: $Message")
    exit 1
}

try {
    $policy = Get-Content -LiteralPath $PolicyPath -Raw -Encoding utf8 |
        ConvertFrom-Json -Depth 20
} catch {
    Fail-AclPolicy "SEC-ACL-POLICY" "the credential ACL policy is unavailable"
}

if (
    $policy.schema_version -ne "armi.windows-credential-acl.v1" -or
    $policy.active -ne $false -or
    $policy.activation_step -ne "M0-S045" -or
    @($policy.allowed_control_sids).Count -ne 2 -or
    @($policy.forbidden_broad_sids).Count -ne 3
) {
    Fail-AclPolicy "SEC-ACL-POLICY" "the credential ACL policy has drifted"
}

if ([string]::IsNullOrEmpty($Sddl)) {
    [Console]::Out.WriteLine("windows-credential-acl-policy: pass (inactive until M0-S045)")
    exit 0
}
if ([string]::IsNullOrEmpty($ExpectedReaderSid)) {
    Fail-AclPolicy "SEC-ACL-READER" "an expected reader SID is required"
}

try {
    $descriptor = [System.Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
} catch {
    Fail-AclPolicy "SEC-ACL-SDDL" "the security descriptor is malformed"
}
if (($descriptor.ControlFlags -band [System.Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -eq 0) {
    Fail-AclPolicy "SEC-ACL-INHERITANCE" "credential ACL inheritance must be disabled"
}

$expectedAllow = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
foreach ($sid in @($policy.allowed_control_sids) + @($ExpectedReaderSid)) {
    [void]$expectedAllow.Add([string]$sid)
}
$actualAllow = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
$fullControlMask = [int][System.Security.AccessControl.FileSystemRights]::FullControl
$readMask = [int][System.Security.AccessControl.FileSystemRights]::Read

foreach ($ace in $descriptor.DiscretionaryAcl) {
    $sid = $ace.SecurityIdentifier.Value
    if (@($policy.forbidden_broad_sids) -contains $sid) {
        Fail-AclPolicy "SEC-ACL-BROAD" "a broad principal is present"
    }
    if ($ace.AceType -ne [System.Security.AccessControl.AceType]::AccessAllowed) {
        Fail-AclPolicy "SEC-ACL-ACE" "only explicit allow entries are permitted"
    }
    if (($ace.AceFlags -band [System.Security.AccessControl.AceFlags]::Inherited) -ne 0) {
        Fail-AclPolicy "SEC-ACL-INHERITANCE" "inherited credential ACEs are forbidden"
    }
    $expectedMask = if (@($policy.allowed_control_sids) -contains $sid) {
        $fullControlMask
    } else {
        $readMask
    }
    if ($ace.AccessMask -ne $expectedMask) {
        Fail-AclPolicy "SEC-ACL-RIGHTS" "credential access rights have drifted"
    }
    [void]$actualAllow.Add($sid)
}

if (-not $actualAllow.SetEquals($expectedAllow)) {
    Fail-AclPolicy "SEC-ACL-READER" "the credential reader matrix has drifted"
}

[Console]::Out.WriteLine("windows-credential-acl-policy: pass (synthetic descriptor only)")
