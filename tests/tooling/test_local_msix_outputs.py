import subprocess
from pathlib import Path


def test_local_msix_retention_and_cleanup_boundaries(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "dist"
    for name in ("0.1.0.9", "0.1.0.10", "notes"):
        directory = output / name
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text(name, encoding="utf-8")
    staging = output / "0.1.0.10" / "staging"
    staging.mkdir()
    (staging / "payload.txt").write_text("temporary", encoding="utf-8")
    outside = tmp_path / "dist-other"
    outside.mkdir()
    (outside / "keep.txt").write_text("outside", encoding="utf-8")
    script = tmp_path / "verify.ps1"
    script.write_text(
        r"""param($Helper, $Root, $Outside)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. $Helper
Clear-LocalMsixHistory -Root $Root -KeepVersion '0.1.0.10'
Remove-LocalMsixDirectory -Root $Root -Path (Join-Path $Root '0.1.0.10/staging')
Remove-LocalMsixDirectory -Root $Root -Path (Join-Path $Root 'missing')
foreach ($target in @($Root, $Outside, (Join-Path $Root '../dist-other'))) {
    try {
        Remove-LocalMsixDirectory -Root $Root -Path $target
        throw 'Boundary was not enforced'
    } catch {
        if ($_.Exception.Message -ne 'LOCAL-MSIX-CLEANUP-BOUNDARY') { throw }
    }
}
$junction = Join-Path $Root '0.1.0.10/junction'
New-Item -ItemType Junction -Path $junction -Target $Outside | Out-Null
try {
    Remove-LocalMsixDirectory -Root $Root -Path (Join-Path $Root '0.1.0.10')
    throw 'Junction was not rejected'
} catch {
    if ($_.Exception.Message -ne 'LOCAL-MSIX-CLEANUP-REPARSE') { throw }
} finally {
    Remove-Item -LiteralPath $junction -Force
}
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(script),
            str(root / "tools/local_msix_outputs.ps1"),
            str(output),
            str(outside),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in output.iterdir()) == ["0.1.0.10", "notes"]
    assert not staging.exists()
    assert (output / "0.1.0.10/keep.txt").read_text() == "0.1.0.10"
    assert (output / "notes/keep.txt").read_text() == "notes"
    assert (outside / "keep.txt").read_text() == "outside"
