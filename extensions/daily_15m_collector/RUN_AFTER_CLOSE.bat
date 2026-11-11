@echo off
cd /d "%~dp0"
python collector.py --config config.json
exit /b %ERRORLEVEL%
