#requires -Version 7.0
param(
    [ValidateSet('alpha', 'beta')]
    [string]$Variant = 'beta'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$out = Join-Path $repo 'dist'
$dockerfile = Join-Path $PSScriptRoot 'Dockerfile'
& docker build --tag ec-systemcore-build --file "$dockerfile" "$PSScriptRoot"
if ($LASTEXITCODE -ne 0) { throw "docker build failed ($LASTEXITCODE)" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& docker run --rm `
    --mount "type=bind,source=$repo,target=/src,readonly" `
    --mount 'type=volume,source=ec-systemcore-cache,target=/cache' `
    --mount "type=bind,source=$out,target=/out" `
    --env SC_CACHE=/cache --env SC_OUT=/out `
    ec-systemcore-build bash /src/systemcore/build.sh $Variant
if ($LASTEXITCODE -ne 0) { throw "docker run failed ($LASTEXITCODE)" }
