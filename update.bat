@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: ============================================================
:: keyword-dashboard  update.bat
:: Pull latest code from GitHub, verify deps, restart Streamlit
:: ============================================================

set "PORT=8501"
set "PYTHON=C:\Users\이선호(reinalee)\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "DASHBOARD=dashboard.py"
set "REMOTE=origin"
set "BRANCH=main"

echo.
echo ============================================================
echo  keyword-dashboard  -  Update and Restart
echo ============================================================
echo.

:: ── Current state ───────────────────────────────────────────
echo [INFO] Current branch:
git branch --show-current
echo.
echo [INFO] HEAD before update:
git log -1 --oneline
set HEAD_BEFORE=
for /f "tokens=*" %%a in ('git log -1 --format^=%%h') do set HEAD_BEFORE=%%a
echo.

:: ── Guard: uncommitted local changes ────────────────────────
git diff --quiet 2>nul
if errorlevel 1 (
    echo [WARNING] Uncommitted local changes detected.
    echo  Run  git status  to review.
    echo  Commit or stash changes, then re-run update.bat.
    goto :FAIL
)
git diff --cached --quiet 2>nul
if errorlevel 1 (
    echo [WARNING] Staged but uncommitted changes detected.
    echo  Commit or reset staged changes, then re-run.
    goto :FAIL
)

:: ── 1/4  Fetch ──────────────────────────────────────────────
echo [1/4] Fetching from %REMOTE%/%BRANCH% ...
git fetch %REMOTE% %BRANCH% 2>&1
if errorlevel 1 (
    echo [WARNING] git fetch failed. Check internet / VPN.
    echo  Continuing with local code only.
)
echo.

:: ── 2/4  Pull (fast-forward only) ───────────────────────────
echo [2/4] Pulling (fast-forward only) ...
git pull --ff-only %REMOTE% %BRANCH% 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Pull failed - not a fast-forward or conflict.
    echo  Resolve manually:  git status / git log
    echo  Do NOT use git reset --hard without reviewing changes.
    goto :FAIL
)
echo.

echo [INFO] HEAD after update:
git log -1 --oneline
echo.

:: ── ba190d3 check ───────────────────────────────────────────
git merge-base --is-ancestor ba190d3 HEAD 2>nul
if errorlevel 1 (
    echo [INFO] ba190d3 is NOT in current history.
) else (
    echo [INFO] ba190d3 confirmed in current history.
)
echo.

:: ── 3/4  Dependencies ───────────────────────────────────────
echo [3/4] Checking dependencies ...
if exist requirements.txt (
    "%PYTHON%" -m pip install -r requirements.txt -q 2>&1
    if errorlevel 1 (
        echo [WARNING] pip install reported errors - check requirements.txt
    ) else (
        echo  Dependencies OK.
    )
) else (
    echo  requirements.txt not found - skipping.
)
echo.

:: ── Syntax check ────────────────────────────────────────────
echo [CHECK] Verifying %DASHBOARD% syntax ...
"%PYTHON%" -m py_compile %DASHBOARD% 2>&1
if errorlevel 1 (
    echo [ERROR] SyntaxError in %DASHBOARD% - aborting restart.
    goto :FAIL
)
echo  %DASHBOARD% OK.
echo.

:: ── 4/4  Restart Streamlit ──────────────────────────────────
echo [4/4] Restarting Streamlit on port %PORT% ...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    echo  Stopping PID %%a on port %PORT% ...
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

start "" "%PYTHON%" -m streamlit run %DASHBOARD% --server.port %PORT% --server.headless true --browser.gatherUsageStats false
timeout /t 4 /nobreak >nul

echo.
echo ============================================================
echo  Update complete!
echo  Branch : %BRANCH%
echo  Before : %HEAD_BEFORE%
echo  After  :
git log -1 --format="  %%h  %%s"
echo  Port   : %PORT%
echo  URL    : http://localhost:%PORT%
echo ============================================================
echo.
start "" "http://localhost:%PORT%"
goto :END

:FAIL
echo.
echo  [FAIL] Update aborted. No code changes or restarts applied.
echo.

:END
echo.
pause