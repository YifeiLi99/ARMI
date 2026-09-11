function Remove-LocalMsixDirectory {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root)

    $boundary = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $target = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if (-not $target.StartsWith($boundary + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'LOCAL-MSIX-CLEANUP-BOUNDARY'
    }
    # Do not traverse a redirected build root or a junction inside an output tree.
    for ($ancestor = $target; $ancestor; $ancestor = [IO.Path]::GetDirectoryName($ancestor)) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'LOCAL-MSIX-CLEANUP-REPARSE'
        }
    }
    if (Test-Path -LiteralPath $target) {
        if (Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint) {
            throw 'LOCAL-MSIX-CLEANUP-REPARSE'
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

function Clear-LocalMsixHistory {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$KeepVersion)

    foreach ($directory in Get-ChildItem -LiteralPath $Root -Directory) {
        if ($directory.Name -match '^\d+\.\d+\.\d+\.\d+$' -and $directory.Name -ne $KeepVersion) {
            Remove-LocalMsixDirectory -Path $directory.FullName -Root $Root
        }
    }
}
