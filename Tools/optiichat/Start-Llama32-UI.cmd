@echo off
setlocal
set "UI_PYTHON=%LOCALAPPDATA%\OptiiChat\python\pythonw.exe"
if not exist "%UI_PYTHON%" set "UI_PYTHON=%LOCALAPPDATA%\OptiiChat\runtime\Scripts\pythonw.exe"
if not exist "%UI_PYTHON%" set "UI_PYTHON=%LOCALAPPDATA%\Programs\Ollama-Llama32-Compat\ui-venv\Scripts\pythonw.exe"
if not exist "%UI_PYTHON%" (
  echo Run Install-OptiiChat.cmd first to install the Python dependencies.
  pause
  exit /b 1
)
set "APP_ENTRY=%~dp0opti_bootstrap.py"
if exist "%LOCALAPPDATA%\OptiiChat\app\opti_bootstrap.py" set "APP_ENTRY=%LOCALAPPDATA%\OptiiChat\app\opti_bootstrap.py"
start "" "%UI_PYTHON%" "%APP_ENTRY%"
