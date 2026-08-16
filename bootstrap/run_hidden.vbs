Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python -m uvicorn api.server:app --host 0.0.0.0 --port 8000", 0, False
