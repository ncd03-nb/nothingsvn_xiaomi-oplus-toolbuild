param(
    [string]$Source = 'D:\Downloads\AyuGram Desktop',
    [string]$Destination = (Join-Path $PSScriptRoot '..\assets\local')
)

$ErrorActionPreference = 'Stop'
$sourcePath = [IO.Path]::GetFullPath($Source)
$destinationPath = [IO.Path]::GetFullPath($Destination)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "AyuGram asset directory not found: $sourcePath"
}
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

$mappings = @(
    @{ From = 'femboyAidL'; To = 'femboyAidL' },
    @{ From = 'overlay\overlay'; To = 'overlay' },
    @{ From = 'system_ext\system_ext'; To = 'system_ext' },
    @{ From = 'vendor\vendor'; To = 'vendor' }
)
foreach ($mapping in $mappings) {
    $from = Join-Path $sourcePath $mapping.From
    $to = Join-Path $destinationPath $mapping.To
    if (-not (Test-Path -LiteralPath $from -PathType Container)) {
        Write-Warning "Skip missing source: $from"
        continue
    }
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Copy-Item -Path (Join-Path $from '*') -Destination $to -Recurse -Force
    Write-Host "Imported $from -> $to"
}
