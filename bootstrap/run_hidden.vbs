Set objShell = CreateObject("WScript.Shell")
objShell.Run "cmd /c cd /d C:\Users\Carl\Jarvis && ""C:\Program Files\Python312\python.exe"" -m uvicorn api.server:app --host 0.0.0.0 --port 8000", 0, False
