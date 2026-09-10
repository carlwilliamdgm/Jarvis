# Dependency graph generation
$outputPath = Join-Path -Path $PSScriptRoot "..\\audit_results\\dependency_graph.png"
# Ensure pipdeptree is installed
pipdeptree --graph-output png > $outputPath
Write-Host "Dependency graph saved to $outputPath"
