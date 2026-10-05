# Static analysis script for Jarvis project
# Uses flake8 to lint all Python files and writes report to audit_results/flake8_report.txt

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$auditResultsDir = Join-Path $projectRoot "audit_results"

# Ensure audit_results directory exists
if (-Not (Test-Path -Path $auditResultsDir)) {
    New-Item -ItemType Directory -Path $auditResultsDir | Out-Null
}

# Run flake8 and redirect output (exclude virtual environments and git)
$reportPath = Join-Path $auditResultsDir "flake8_report.txt"
flake8 $projectRoot --exclude=.venv,venv,venv_isolated,.git,__pycache__ > $reportPath 2>&1
