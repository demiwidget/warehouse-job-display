$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$LauncherPath = Join-Path $ProjectDir "Warehouse Remote Manager.vbs"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Warehouse Remote Manager.lnk"

if (-not (Test-Path $LauncherPath)) {
    throw "Cannot find launcher: $LauncherPath"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
$Shortcut.Arguments = '"' + $LauncherPath + '"'
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.IconLocation = Join-Path $env:WINDIR "System32\imageres.dll,109"
$Shortcut.Description = "Warehouse Remote Manager"
$Shortcut.Save()

Write-Host "Created shortcut: $ShortcutPath"
