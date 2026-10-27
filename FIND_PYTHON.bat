@echo off
set "QTA_PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" (
 "%~dp0.venv\Scripts\python.exe" -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
 if not errorlevel 1 (
  set QTA_PYTHON="%~dp0.venv\Scripts\python.exe"
  exit /b 0
 )
)
py -3.12 -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
 set "QTA_PYTHON=py -3.12"
 exit /b 0
)
py -3 -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
 set "QTA_PYTHON=py -3"
 exit /b 0
)
python -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
 set "QTA_PYTHON=python"
 exit /b 0
)
echo Khong tim thay Python 3.11 tro len. Khuyen nghi Python 3.12.
echo Cai Python tu python.org, chon Add python.exe to PATH va mo lai CMD.
exit /b 1
