@echo off
setlocal
cd /d "%~dp0.." || exit /b 4
if not exist logs mkdir logs
if not exist logs exit /b 4
set "PYTHON=%QTA_PYTHON%"
if not defined PYTHON set "PYTHON=%~dp0..\..\..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [%DATE% %TIME%] ERROR: Python executable not found: "%PYTHON%" >> "logs\scheduler_console.log"
    exit /b 4
)
echo [%DATE% %TIME%] START >> "logs\scheduler_console.log"
"%PYTHON%" -X utf8 -B "%CD%\collect_vn30_yahoo.py" --config "%CD%\config.vn30.2026-07.json" --scheduled --fallback-59 >> "logs\scheduler_console.log" 2>&1
set "RESULT=%ERRORLEVEL%"
echo [%DATE% %TIME%] EXIT %RESULT% >> "logs\scheduler_console.log"
exit /b %RESULT%
