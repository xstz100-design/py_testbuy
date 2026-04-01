Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Administrator\Desktop\okxoption-trading\scripts"
WshShell.Run """C:\Users\Administrator\Desktop\okxoption-trading\.venv\Scripts\pythonw.exe"" bot_watchdog.py", 0, False
