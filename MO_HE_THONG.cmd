@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua co moi truong Python. Vui long xem README.md de cai dat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\start_system.py
if errorlevel 1 pause
