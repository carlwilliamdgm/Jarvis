@echo off
cd /d "%~dp0"
if "%~1"=="" (
    "%~dp0.venv\Scripts\python.exe" -m interface_morphique.server
) else (
    "%~dp0.venv\Scripts\python.exe" "%~dp0greatos.py" %*
)
