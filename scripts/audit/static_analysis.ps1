# Static analysis script for Jarvis project
# Uses flake8 to lint all Python files and writes report to audit_results/flake8_report.txt

# Ensure audit_results directory exists
if (-Not (Test-Path -Path "C:\Users\Carl\Jarvis\audit_results")) {
    New-Item -ItemType Directory -Path "C:\Users\Carl\Jarvis\audit_results" | Out-Null
}

# Run flake8 and redirect output (exclude virtual environments and git)
flake8 "C:\Users\Carl\Jarvis" --exclude=.venv,venv,venv_isolated,.git,__pycache__ > "C:\Users\Carl\Jarvis\audit_results\flake8_report.txt" 2>&1
