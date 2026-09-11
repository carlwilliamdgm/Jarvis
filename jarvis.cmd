@echo off
cd /d "%~dp0"
if "%~1"=="" (
    "%~dp0.venv\Scripts\python.exe" -m jarvis.agent
) else (
    "%~dp0.venv\Scripts\python.exe" "%~dp0greatos.py" %*
)
