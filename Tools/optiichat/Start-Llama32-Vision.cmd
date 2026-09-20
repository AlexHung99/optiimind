@echo off
setlocal
set PYTHONUTF8=1
set "UI_PYTHON=%LOCALAPPDATA%\OptiiChat\runtime\Scripts\python.exe"
if not exist "%UI_PYTHON%" set "UI_PYTHON=%LOCALAPPDATA%\Programs\Ollama-Llama32-Compat\ui-venv\Scripts\python.exe"
"%UI_PYTHON%" "%~dp0start_llama32_vision.py"
if errorlevel 1 pause
