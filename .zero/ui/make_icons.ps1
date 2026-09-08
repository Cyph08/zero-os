# Zero OS — Icon Generator
# Run once from K:\Zero\.zero\ui\
# Usage: .\make_icons.ps1

Add-Type -AssemblyName System.Drawing

$iconsDir = Join-Path $PSScriptRoot "src-tauri\icons"
New-Item -ItemType Directory -Force -Path $iconsDir | Out-Null
Write-Host "Icons dir: $iconsDir"

function New-ZeroIcon([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g   = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

    # Background — near-black
    $bg = [System.Drawing.Color]::FromArgb(255, 2, 8, 20)
    $g.Clear($bg)

    $cx  = $size / 2
    $cy  = $size / 2
    $pad = [int]($size * 0.04)

    # Outer cyan ring
    $ringW = [Math]::Max(1, [int]($size / 16))
    $ringPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(180, 0, 229, 255), $ringW)
    $g.DrawEllipse($ringPen, $pad, $pad, $size - $pad*2, $size - $pad*2)

    # Inner glow dot
    $dotR = [int]($size / 6)
    $dotBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 0, 229, 255))
    $g.FillEllipse($dotBrush, [int]($cx - $dotR), [int]($cy - $dotR), $dotR*2, $dotR*2)

    # Second ring (dim)
    $ring2W = [Math]::Max(1, [int]($size / 32))
    $ring2Pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(60, 0, 229, 255), $ring2W)
    $innerPad = [int]($size * 0.18)
    $g.DrawEllipse($ring2Pen, $innerPad, $innerPad, $size - $innerPad*2, $size - $innerPad*2)

    $g.Dispose()
    return $bmp
}

# PNG sizes
$pngSizes = @(
    @{ size = 32;  name = "32x32.png" },
    @{ size = 128; name = "128x128.png" },
    @{ size = 256; name = "128x128@2x.png" }
)

foreach ($entry in $pngSizes) {
    $bmp  = New-ZeroIcon $entry.size
    $path = Join-Path $iconsDir $entry.name
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host "  Created $($entry.name)"
}

# ICO — embed 16, 32, 48, 256 sizes
# ICO format header + directory + BMP data (PNG-in-ICO for 256)
function Write-IcoFile([string]$outPath) {
    $sizes = @(16, 32, 48, 256)
    $bmps  = $sizes | ForEach-Object { New-ZeroIcon $_ }

    # Encode each image as PNG bytes into memory streams
    $streams = $bmps | ForEach-Object {
        $ms = New-Object System.IO.MemoryStream
        $_.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $ms
    }

    $fs = [System.IO.File]::OpenWrite($outPath)
    $bw = New-Object System.IO.BinaryWriter($fs)

    # ICO header
    $bw.Write([uint16]0)        # reserved
    $bw.Write([uint16]1)        # type: ICO
    $bw.Write([uint16]$sizes.Count)

    # Calculate offsets — header=6, directory=16*count
    $dirSize  = 16 * $sizes.Count
    $dataOffset = 6 + $dirSize

    $offsets = @()
    $offset  = $dataOffset
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $offsets += $offset
        $offset  += $streams[$i].Length
    }

    # Directory entries
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $sz = $sizes[$i]
        $wh = if ($sz -lt 256) { $sz } else { 0 }
        $bw.Write([byte]$wh)   # width  (0 = 256)
        $bw.Write([byte]$wh)   # height
        $bw.Write([byte]0)                           # colour count
        $bw.Write([byte]0)                           # reserved
        $bw.Write([uint16]1)                         # planes
        $bw.Write([uint16]32)                        # bit count
        $bw.Write([uint32]$streams[$i].Length)       # size of image data
        $bw.Write([uint32]$offsets[$i])              # offset
    }

    # Image data
    foreach ($ms in $streams) {
        $bw.Write($ms.ToArray())
        $ms.Dispose()
    }

    $bw.Dispose()
    $fs.Dispose()
    $bmps | ForEach-Object { $_.Dispose() }
    Write-Host "  Created icon.ico"
}

Write-IcoFile (Join-Path $iconsDir "icon.ico")

# ICNS stub — macOS icon, not used in Windows build but Tauri conf lists it.
# Minimal valid ICNS: just the magic bytes + length + one ic08 chunk (128x128 PNG).
function Write-IcnsStub([string]$outPath) {
    $bmp = New-ZeroIcon 128
    $ms  = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    $pngBytes = $ms.ToArray()
    $ms.Dispose()

    $chunkType = [System.Text.Encoding]::ASCII.GetBytes("ic07")  # 128x128
    $chunkSize = 8 + $pngBytes.Length

    $totalSize = 8 + $chunkSize

    $fs = [System.IO.File]::OpenWrite($outPath)
    $bw = New-Object System.IO.BinaryWriter($fs)

    # ICNS magic
    $bw.Write([System.Text.Encoding]::ASCII.GetBytes("icns"))
    # Big-endian total size
    $bw.Write([byte](($totalSize -shr 24) -band 0xFF))
    $bw.Write([byte](($totalSize -shr 16) -band 0xFF))
    $bw.Write([byte](($totalSize -shr 8)  -band 0xFF))
    $bw.Write([byte]($totalSize           -band 0xFF))

    # Chunk type
    $bw.Write($chunkType)
    # Chunk size (big-endian)
    $bw.Write([byte](($chunkSize -shr 24) -band 0xFF))
    $bw.Write([byte](($chunkSize -shr 16) -band 0xFF))
    $bw.Write([byte](($chunkSize -shr 8)  -band 0xFF))
    $bw.Write([byte]($chunkSize           -band 0xFF))
    # PNG data
    $bw.Write($pngBytes)

    $bw.Dispose()
    $fs.Dispose()
    Write-Host "  Created icon.icns"
}

Write-IcnsStub (Join-Path $iconsDir "icon.icns")

Write-Host ""
Write-Host "All icons generated. Now run: npm run tauri:dev"
