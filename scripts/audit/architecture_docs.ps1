# Architecture documentation generation
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outDir = Join-Path -Path $PSScriptRoot '..\audit_results\architecture'
if (-Not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
pdoc --html $projectRoot --output-dir $outDir
Write-Host "Architecture docs written to $outDir"
