import json
import subprocess
from pathlib import Path


def test_calendar_msix_version_allocation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = tmp_path / "versions.ps1"
    script.write_text(
        r"""param($Helper)
$ErrorActionPreference = 'Stop'
. $Helper
$results = @(
    (Get-LocalMsixVersion -Highest '0.1.0.30' -BuildDate '2026-09-15'),
    (Get-LocalMsixVersion -Highest '2026.9.15.0' -BuildDate '2026-09-15'),
    (Get-LocalMsixVersion -Highest '2026.9.15.9' -BuildDate '2026-09-15'),
    (Get-LocalMsixVersion -Highest '2026.9.15.65535' -BuildDate '2026-09-16'),
    (Get-LocalMsixVersion -Highest '2026.9.30.7' -BuildDate '2026-10-01'),
    (Get-LocalMsixVersion -Highest '2026.12.31.3' -BuildDate '2027-01-01')
)
foreach ($case in @(
    @('2026.9.16.1', 'LOCAL-MSIX-VERSION-DATE-BEHIND'),
    @('2026.9.15.65535', 'LOCAL-MSIX-VERSION-EXHAUSTED')
)) {
    try {
        Get-LocalMsixVersion -Highest $case[0] -BuildDate '2026-09-15'
        throw 'Expected version allocation failure'
    } catch {
        if ($_.Exception.Message -ne $case[1]) { throw }
    }
}
$results | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(script),
            str(root / "tools/local_msix_version.ps1"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(result.stdout) == [
        "2026.9.15.1",
        "2026.9.15.1",
        "2026.9.15.10",
        "2026.9.16.1",
        "2026.10.1.1",
        "2027.1.1.1",
    ]
