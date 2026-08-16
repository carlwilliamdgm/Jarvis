Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\launch_hidden.py"
objShell.Run "C:\Program Files\Python312\pythonw.exe """ & scriptPath & """", 0, False
