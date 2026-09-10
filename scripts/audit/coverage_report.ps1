# Coverage report using pytest
$covDir = Join-Path -Path $PSScriptRoot "..\audit_results\coverage"
if (-Not (Test-Path $covDir)) { New-Item -ItemType Directory -Path $covDir | Out-Null }
pytest --cov=. --cov-report=html:$covDir
Write-Host "Coverage HTML report written to $covDir"
