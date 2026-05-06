@echo off
set /p MANAGER_URL=Manager Pi IP or URL, for example 192.168.1.50:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_remote_manager_app.ps1" -ManagerUrl "%MANAGER_URL%"
if errorlevel 1 pause
