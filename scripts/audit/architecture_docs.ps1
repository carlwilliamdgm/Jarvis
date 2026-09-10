# Architecture documentation generation
$outDir = Join-Path -Path $PSScriptRoot '..\audit_results\architecture'
if (-Not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
pdoc --html "C:\Users\Carl\Jarvis" --output-dir $outDir
Write-Host "Architecture docs written to $outDir"
