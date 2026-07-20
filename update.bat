@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ======================================
echo  키워드 대시보드 - 업데이트 Push
echo ======================================
echo.

:: 원격 최신 변경사항 먼저 가져오기
echo [PRE] 원격 변경사항 확인 중...
git fetch origin main 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] 원격 서버 연결 실패. 인터넷/VPN 연결을 확인하세요.
    echo  로컬 커밋만 진행합니다.
    echo.
)

:: 로컬에 스테이징할 변경사항 확인
git diff --quiet 2>nul
git diff --cached --quiet 2>nul
git status --porcelain > "%TEMP%\kd_status.txt" 2>nul

for %%f in ("%TEMP%\kd_status.txt") do (
    if %%~zf == 0 (
        echo ============================================================
        echo  [INFO] 변경된 파일이 없습니다. 이미 최신 상태입니다.
        echo ============================================================
        del "%TEMP%\kd_status.txt" 2>nul
        goto :PUSH_ONLY
    )
)
del "%TEMP%\kd_status.txt" 2>nul

:: 날짜 생성
for /f "tokens=*" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set DATETIME=%%a
set COMMIT_MSG=Data update %DATETIME%
echo Commit: %COMMIT_MSG%
echo.

:: 스테이징
echo [1/3] 변경 파일 스테이징 중...
git add -A
if errorlevel 1 (
    echo.
    echo [ERROR] git add 실패. Git이 설치되어 있는지 확인하세요.
    goto :FAIL
)

echo 스테이징된 파일:
git diff --cached --name-only
echo.

:: 스테이징 후 재확인
git diff --cached --quiet 2>nul
if not errorlevel 1 (
    echo ============================================================
    echo  [INFO] 스테이징된 변경사항이 없습니다.
    echo ============================================================
    goto :PUSH_ONLY
)

:: 커밋
echo [2/3] 커밋 생성 중...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo.
    echo [ERROR] 커밋 실패.
    goto :FAIL
)

:PUSH_ONLY
:: 원격과 비교해서 push할 커밋이 있는지 확인
git log origin/main..HEAD --oneline > "%TEMP%\kd_ahead.txt" 2>nul
for %%f in ("%TEMP%\kd_ahead.txt") do (
    if %%~zf == 0 (
        echo ============================================================
        echo  [INFO] 이미 원격과 동기화되어 있습니다. Push 불필요.
        echo ============================================================
        del "%TEMP%\kd_ahead.txt" 2>nul
        goto :END
    )
)
del "%TEMP%\kd_ahead.txt" 2>nul

:: Pull --rebase 후 Push
echo [3/3] GitHub에 업로드 중...
git pull --rebase origin main 2>&1
if errorlevel 1 (
    echo.
    echo ============================================================
    echo  [ERROR] Pull 중 충돌 발생.
    echo  git rebase --abort 실행 후 수동으로 해결하세요.
    echo ============================================================
    goto :FAIL
)

git push origin main
set PUSH_RESULT=%errorlevel%

if %PUSH_RESULT% neq 0 (
    echo.
    echo ============================================================
    echo  [ERROR] Push 실패 (오류코드: %PUSH_RESULT%)
    echo.
    echo  주요 원인:
    echo   1) 인터넷/VPN 연결 확인
    echo   2) 현재 브랜치 확인: git branch
    echo   3) 권한 오류: GitHub 인증 확인
    echo ============================================================
    goto :FAIL
)

echo.
echo ============================================================
echo  [SUCCESS] 업로드 완료!
echo  Streamlit Cloud가 2~5분 내 자동 재배포됩니다.
echo  대시보드에서 F5를 눌러 새로고침하세요.
echo ============================================================
goto :END

:FAIL
echo.
echo  문제가 지속되면 커뮤니케이션팀에 문의하세요.

:END
echo.
pause
