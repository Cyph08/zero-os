' ============================================================
'  Zero OS — silent launcher
'
'  Starts the backend (and with it the Telegram bot) with no
'  console window. A shortcut to this file lives in the Windows
'  Startup folder, so Zero comes up on its own when you log in
'  and you never have to start it by hand.
'
'  To stop Zero:      stop-zero.bat
'  To disable autostart: delete the shortcut from
'    shell:startup   (Win+R, type shell:startup)
' ============================================================

Set shell = CreateObject("WScript.Shell")

' 0 = hidden window, False = don't wait for it to exit
shell.CurrentDirectory = "K:\Zero\.zero"
shell.Run """K:\Zero\.venv\Scripts\python.exe"" -m uvicorn api.main:app --host 127.0.0.1 --port 8000", 0, False
