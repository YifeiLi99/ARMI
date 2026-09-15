[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $root 'apps/armi-admin/src/armi_admin/icon_resources'
$web = Join-Path $root 'apps/armi-creator-web/src/app'
New-Item -ItemType Directory -Path $destination, $web -Force | Out-Null
Add-Type -AssemblyName System.Drawing
$source = [Drawing.Bitmap]::new((Join-Path $root 'assets/armi-avatar-pixel.png'))
try {
    $frames = @{}
    foreach ($size in @(16, 20, 24, 32, 40, 44, 48, 50, 64, 128, 150, 256)) {
        $bitmap = [Drawing.Bitmap]::new($size, $size, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        $stream = [IO.MemoryStream]::new()
        try {
            $graphics.Clear([Drawing.Color]::Transparent)
            $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
            $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::Half
            $graphics.DrawImage($source, [Drawing.Rectangle]::new(0, 0, $size, $size))
            $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
            $frames[$size] = $stream.ToArray()
        } finally { $stream.Dispose(); $graphics.Dispose(); $bitmap.Dispose() }
    }
    foreach ($asset in @(@('StoreLogo', 50), @('Square44x44Logo', 44), @('Square150x150Logo', 150), @('avatar', 128))) {
        [IO.File]::WriteAllBytes((Join-Path $destination ($asset[0] + '.png')), $frames[[int]$asset[1]])
    }
    [IO.File]::WriteAllBytes((Join-Path $web 'armi-avatar.png'), $frames[64])
    $sizes = @(16, 20, 24, 32, 40, 48, 64, 128, 256)
    $file = [IO.File]::Create((Join-Path $destination 'armi.ico'))
    $writer = [IO.BinaryWriter]::new($file)
    try {
        $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        foreach ($size in $sizes) {
            $edge = [byte]($size % 256)
            $writer.Write($edge); $writer.Write($edge); $writer.Write([byte]0); $writer.Write([byte]0)
            $writer.Write([uint16]1); $writer.Write([uint16]32)
            $writer.Write([uint32]$frames[$size].Length); $writer.Write([uint32]$offset)
            $offset += $frames[$size].Length
        }
        foreach ($size in $sizes) { $writer.Write([byte[]]$frames[$size]) }
    } finally { $writer.Dispose(); $file.Dispose() }
} finally { $source.Dispose() }
