@echo off
set /p MANAGER_URL=Manager Pi URL, for example http://192.168.1.50:8765:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_remote_manager_app.ps1" -ManagerUrl "%MANAGER_URL%"
