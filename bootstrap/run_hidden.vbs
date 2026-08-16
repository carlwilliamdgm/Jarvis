Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "schtasks /Run /TN ""\JarvisAgent""", 0, False
