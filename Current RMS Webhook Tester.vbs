Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
command = "cmd /c """ & root & "\Current RMS Webhook Tester.cmd"""
shell.Run command, 0, False
