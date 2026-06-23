@echo off
chcp 65001 > nul

:: ── 실행 로그 기록 위치 ──────────────────────────────
set LOGFILE=%~dp0logs\collector_log.txt

:: logs 폴더가 없으면 자동 생성
if not exist "%~dp0logs" mkdir "%~dp0logs"

:: ── 실행 시작 ────────────────────────────────────────
echo ============================================ >> "%LOGFILE%"
echo 실행 시각: %date% %time% >> "%LOGFILE%"
echo ============================================ >> "%LOGFILE%"

:: Python 경로 자동 탐지 후 collector.py 실행
python "%~dp0collector.py" >> "%LOGFILE%" 2>&1

echo 종료 시각: %date% %time% >> "%LOGFILE%"
echo. >> "%LOGFILE%"
