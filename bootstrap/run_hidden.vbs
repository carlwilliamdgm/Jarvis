Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -WindowStyle Hidden -Command ""cd 'C:\Users\Carl\Jarvis'; & 'C:\Program Files\Python312\python.exe' -m uvicorn api.server:app --host 0.0.0.0 --port 8000""", 0, False
