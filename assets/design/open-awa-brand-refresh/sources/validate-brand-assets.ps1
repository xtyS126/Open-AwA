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

$svg_names = @(
    'icon-master.svg',
    'icon-circle.svg',
    'icon-mark.svg',
    'icon-construction.svg',
    'favicon.svg',
    'android-adaptive-foreground.svg',
    'android-adaptive-background.svg',
    'android-adaptive-monochrome.svg'
)

foreach ($name in $svg_names) {
    $path = Join-Path $brand_directory $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing SVG: $name"
    }

    [xml]$document = Get-Content -Raw -Encoding utf8 -LiteralPath $path
    $forbidden_nodes = $document.SelectNodes("//*[local-name()='image' or local-name()='filter' or local-name()='script']")
    if ($forbidden_nodes.Count -gt 0) {
        throw "SVG contains a forbidden dependency or executable node: $name"
    }

    foreach ($node in $document.SelectNodes('//*')) {
        foreach ($attribute in $node.Attributes) {
            if ($attribute.LocalName -eq 'href' -and -not $attribute.Value.StartsWith('#')) {
                throw "SVG contains an external reference: $name"
            }
        }
    }
}

$expected_pngs = [ordered]@{
    'icon-1024.png' = 1024
    'icon-512.png' = 512
    'icon-256.png' = 256
    'icon-128.png' = 128
    'icon-64.png' = 64
    'icon-48.png' = 48
    'icon-32.png' = 32
    'icon-16.png' = 16
    'favicon-32.png' = 32
    'favicon-16.png' = 16
}

foreach ($entry in $expected_pngs.GetEnumerator()) {
    $path = Join-Path $brand_directory $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing PNG: $($entry.Key)"
    }

    $dimensions = (& $MagickPath 'identify' '-format' '%wx%h' $path).Trim()
    $expected_dimensions = "$($entry.Value)x$($entry.Value)"
    if ($dimensions -ne $expected_dimensions) {
        throw "Invalid PNG dimensions for $($entry.Key): got $dimensions, expected $expected_dimensions"
    }

    $channels = (& $MagickPath 'identify' '-format' '%[channels]' $path).Trim()
    if ($channels -notmatch 'a') {
        throw "PNG has no alpha channel: $($entry.Key), channels $channels"
    }

    $alpha_range = (& $MagickPath $path '-alpha' 'extract' '-format' '%[fx:minima],%[fx:maxima]' 'info:').Trim().Split(',')
    if ([double]$alpha_range[0] -ge 0.01 -or [double]$alpha_range[1] -le 0.99) {
        throw "Invalid PNG alpha range for $($entry.Key): $($alpha_range -join ',')"
    }
}

$ico_path = Join-Path $brand_directory 'open-awa.ico'
if (-not (Test-Path -LiteralPath $ico_path -PathType Leaf)) {
    throw 'Missing Windows ICO: open-awa.ico'
}

$ico_frames = (& $MagickPath 'identify' '-format' "%wx%h`n" $ico_path) -split "`r?`n" | Where-Object { $_ }
foreach ($size in @(256, 128, 64, 48, 32, 16)) {
    $expected_frame = "${size}x${size}"
    if ($ico_frames -notcontains $expected_frame) {
        throw "ICO is missing frame: $expected_frame"
    }
}

Write-Output "SVG XML and dependency checks passed: $($svg_names.Count) files"
Write-Output "PNG dimension, RGBA, and alpha checks passed: $($expected_pngs.Count) files"
Write-Output "ICO multi-size checks passed: $($ico_frames -join ', ')"
