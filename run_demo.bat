@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer, or run health_demo.py using your Python interpreter.
  pause
  exit /b 1
)
set "DEMO_OUTPUT=demo_%RANDOM%_%RANDOM%"
py -3 health_demo.py --demo --start 2026-10-01 --end 2026-10-14 --out "%DEMO_OUTPUT%"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "%DEMO_OUTPUT%\report.html"
pause
