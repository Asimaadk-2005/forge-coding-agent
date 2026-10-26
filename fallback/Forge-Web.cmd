@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Extract the complete Forge-Web package, including the runtime folder.
  pause
  exit /b 1
)
"runtime\python.exe" -B "fallback\web_agent.py" %*
if errorlevel 1 pause
