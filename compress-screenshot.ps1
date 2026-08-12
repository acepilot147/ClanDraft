# Recompresses a raid scoreboard screenshot for low-footprint storage in
# Screenshots/. Downscales to a max width and re-encodes as quality-40 JPEG;
# a 1700px dark Roblox scoreboard lands around 50-80 KB. Prints the SHA-256
# of the ORIGINAL file (that hash goes in Games.csv, so the stored image can
# be recompressed later without breaking provenance/dedup).
#
#   powershell -File compress-screenshot.ps1 -In <original.png> -GameId M8
param(
    [Parameter(Mandatory = $true)][string]$In,
    [Parameter(Mandatory = $true)][string]$GameId,
    [int]$MaxWidth = 1400,
    [int]$Quality = 40
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $repo "Screenshots"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory $outDir | Out-Null }
$out = Join-Path $outDir "$GameId.jpg"

$sha = (Get-FileHash -Algorithm SHA256 $In).Hash.ToLower()

$src = [System.Drawing.Image]::FromFile((Resolve-Path $In))
try {
    $w = [Math]::Min($src.Width, $MaxWidth)
    $h = [int][Math]::Round($src.Height * ($w / $src.Width))
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($src, 0, 0, $w, $h)
    $g.Dispose()

    $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
        Where-Object { $_.MimeType -eq "image/jpeg" }
    $params = New-Object System.Drawing.Imaging.EncoderParameters 1
    $params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter(
        [System.Drawing.Imaging.Encoder]::Quality, [long]$Quality)
    $bmp.Save($out, $codec, $params)
    $bmp.Dispose()
}
finally { $src.Dispose() }

$kb = [Math]::Round((Get-Item $out).Length / 1KB)
Write-Output "stored   $out (${kb} KB)"
Write-Output "sha256   $sha"
