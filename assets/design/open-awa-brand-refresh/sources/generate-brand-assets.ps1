param(
    [string]$MagickPath
)

$ErrorActionPreference = 'Stop'

$source_directory = Split-Path -Parent $MyInvocation.MyCommand.Path
$asset_directory = Split-Path -Parent $source_directory
$brand_directory = Join-Path $asset_directory 'brand'

if (-not $MagickPath) {
    $magick_command = Get-Command 'magick' -ErrorAction SilentlyContinue
    if (-not $magick_command) {
        throw 'ImageMagick 7 command magick was not found.'
    }
    $MagickPath = $magick_command.Source
}

function Invoke-ImageMagick {
    param([string[]]$Arguments)

    & $MagickPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "ImageMagick failed with exit code $LASTEXITCODE."
    }
}

$master_svg = Join-Path $brand_directory 'icon-master.svg'
$favicon_svg = Join-Path $brand_directory 'favicon.svg'
$icon_sizes = @(1024, 512, 256, 128, 64, 48, 32, 16)

foreach ($size in $icon_sizes) {
    $output_path = Join-Path $brand_directory "icon-$size.png"
    Invoke-ImageMagick @(
        '-background', 'none',
        '-density', '384',
        $master_svg,
        '-resize', "${size}x${size}",
        '-colorspace', 'sRGB',
        '-strip',
        "PNG32:$output_path"
    )
}

foreach ($size in @(32, 16)) {
    $output_path = Join-Path $brand_directory "favicon-$size.png"
    Invoke-ImageMagick @(
        '-background', 'none',
        '-density', '384',
        $favicon_svg,
        '-resize', "${size}x${size}",
        '-colorspace', 'sRGB',
        '-strip',
        "PNG32:$output_path"
    )
}

$ico_sources = @(256, 128, 64, 48, 32, 16) | ForEach-Object {
    Join-Path $brand_directory "icon-$_.png"
}
$ico_path = Join-Path $brand_directory 'open-awa.ico'
Invoke-ImageMagick (@($ico_sources) + @('-define', 'icon:auto-resize=256,128,64,48,32,16', $ico_path))

$validation_script = Join-Path $source_directory 'validate-brand-assets.ps1'
& $validation_script -MagickPath $MagickPath
if ($LASTEXITCODE -ne 0) {
    throw "Asset validation failed with exit code $LASTEXITCODE."
}

Write-Output "Brand raster assets were generated and validated: $brand_directory"
