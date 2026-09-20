@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0opti_install.py"
) else (
  python "%~dp0opti_install.py"
)
if errorlevel 1 (
  echo Installation did not complete. Python 3.11+ and Ollama for Windows are required.
  pause
  exit /b 1
)
call "%~dp0Start-OptiiChat.cmd"
