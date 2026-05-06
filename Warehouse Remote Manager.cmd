@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_remote_manager_app.ps1"
if errorlevel 1 pause
