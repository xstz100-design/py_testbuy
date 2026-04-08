Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Administrator\Desktop\BPtrading\scripts"
WshShell.Run """C:\Users\Administrator\Desktop\BPtrading\.venv\Scripts\pythonw.exe"" bot_watchdog.py", 0, False
