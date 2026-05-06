Set shell = CreateObject("WScript.Shell")
scriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & "\scripts\run_remote_manager_app.ps1"" -GuiLaunch"
shell.Run command, 0, False
