@echo off
setlocal
cd /d "%~dp0"
call "%~dp0FIND_PYTHON.bat"
if errorlevel 1 (
 pause
 exit /b 1
)
%QTA_PYTHON% --version
set "QTA_SELECTED_DB=data\state\qta_phase3_test.db"
if not exist "%QTA_SELECTED_DB%" set "QTA_SELECTED_DB=data\state\vietnam_stocks_mock.db"
if not exist "%QTA_SELECTED_DB%" (
 echo Copy qta_phase3_test.db vao thu muc data\state truoc khi chay.
 pause
 exit /b 1
)
%QTA_PYTHON% phase8_data.py --db "%QTA_SELECTED_DB%"
if errorlevel 1 (
 echo Backup hoac migration that bai. Dung khoi dong.
 pause
 exit /b 1
)
echo Dang kiem tra database. Hay dung cac tien trinh dang ghi du lieu.
%QTA_PYTHON% audit_quality.py --db "%QTA_SELECTED_DB%"
if errorlevel 1 (
 echo Audit khong thanh cong. Xem thong bao phia tren.
 pause
 exit /b 1
)
%QTA_PYTHON% web_app.py --price-db "%QTA_SELECTED_DB%"
pause
