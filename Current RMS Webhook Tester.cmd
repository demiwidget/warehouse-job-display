@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m webhook_tester.app --auto-register
) else (
  start "" pythonw -m webhook_tester.app --auto-register
)
