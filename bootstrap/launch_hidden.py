import subprocess
import sys
import os

os.chdir(r"C:\Users\Carl\Jarvis")

# Use CREATE_NO_WINDOW flag to hide the console window
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = subprocess.SW_HIDE

# Launch uvicorn with hidden window
subprocess.Popen(
    [r"C:\Program Files\Python312\python.exe", "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"],
    startupinfo=startupinfo,
    creationflags=subprocess.CREATE_NO_WINDOW
)
