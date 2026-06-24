@echo off
chcp 65001 > nul
title SCK 키워드 트렌드 대시보드

set SCRIPT_DIR=%~dp0
set PYTHON=C:\Users\이선호(reinalee)\AppData\Local\Python\pythoncore-3.14-64\python.exe
set PORT=8501

echo ========================================
echo  SCK 키워드 트렌드 대시보드 시작 중...
echo  주소: http://localhost:%PORT%
echo  종료하려면 이 창을 닫으세요.
echo ========================================

:: 이미 실행 중이면 바로 브라우저만 열기
netstat -ano | findstr ":%PORT% " | findstr LISTENING > nul 2>&1
if %errorlevel% == 0 (
    echo 이미 실행 중입니다. 브라우저를 엽니다...
    start "" "http://localhost:%PORT%"
    exit
)

:: Streamlit 실행
cd /d "%SCRIPT_DIR%"
start "" "%PYTHON%" -m streamlit run dashboard.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

:: 4초 대기 후 브라우저 열기
timeout /t 4 /nobreak > nul
start "" "http://localhost:%PORT%"

echo 브라우저가 열렸습니다.
pause
