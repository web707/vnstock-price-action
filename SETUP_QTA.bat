@echo off
setlocal
cd /d "%~dp0"
if not exist "requirements.txt" (
 echo Hay giai nen TOAN BO ZIP vao mot thu muc truoc khi chay SETUP_QTA.bat.
 pause
 exit /b 1
)
call "%~dp0FIND_PYTHON.bat"
if errorlevel 1 (
 pause
 exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
 %QTA_PYTHON% -m venv ".venv"
 if errorlevel 1 (
  echo Tao moi truong Python that bai.
  pause
  exit /b 1
 )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
 echo Cai thu vien that bai. Can Internet trong lan cai dat dau.
 pause
 exit /b 1
)
call "%~dp0START_QTA.bat"
