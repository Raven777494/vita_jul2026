@echo off
chcp 65001 >nul
title Engine7B 三引擎啟動器 v1.0

:menu
cls
echo.
echo ========================================================
echo   Engine7B 三引擎架構
echo   [1] Platform Engine  - Docker (PostgreSQL + Redis)
echo   [2] Compute Engine   - Seele (LLM 8081-8085)
echo   [3] Logic Engine     - Vita API (FastAPI :8000)
echo ========================================================
echo.
echo   A. 完整啟動 (1 -^> 2 -^> 3)
echo   P. 僅 Platform Engine (Docker)
echo   C. 僅 Compute Engine (Seele)
echo   L. 僅 Logic Engine (Vita API)
echo   S. 關閉所有 Python / Uvicorn 程序
echo   0. 離開
echo.
set "choice="
set /p choice=請輸入選項：

if /i "%choice%"=="A" goto deploy_all
if /i "%choice%"=="P" goto start_platform
if /i "%choice%"=="C" goto start_compute
if /i "%choice%"=="L" goto start_logic
if /i "%choice%"=="S" goto kill_all
if "%choice%"=="0" exit
goto menu

:start_platform
cls
echo [Platform Engine] 啟動 Docker 基礎設施...
cd /d D:\Desktop\engine7b
if not exist config\.env.compose (
    echo [ERROR] 缺少 config\.env.compose
    echo 請先執行: copy config\.env.compose.example config\.env.compose
    pause
    goto menu
)
docker compose --env-file config/.env.compose up -d postgres redis
echo.
echo Platform Engine 就緒 (postgres:5432, redis:6379)
pause
goto menu

:start_compute
cls
echo [Compute Engine] 啟動 Seele Unified Orchestrator...
cd /d D:\Desktop\engine7b
call .engine7b\Scripts\activate.bat
start "Engine7B Compute Engine" cmd /k "python seele_v8_5.py --action deploy"
echo Compute Engine 啟動指令已發送 (ports 8081-8085)
pause
goto menu

:start_logic
cls
echo [Logic Engine] 啟動 Vita FastAPI...
cd /d D:\Desktop\engine7b
call .engine7b\Scripts\activate.bat
start "Engine7B Logic Engine" cmd /k "python -m uvicorn app.main:app_instance --host 127.0.0.1 --port 8000 --reload"
echo Logic Engine 啟動指令已發送 (http://127.0.0.1:8000)
pause
goto menu

:deploy_all
cls
echo ========================================================
echo  Engine7B 三引擎完整啟動
echo ========================================================
cd /d D:\Desktop\engine7b

echo.
echo [Step 1/3] Platform Engine - Docker...
if not exist config\.env.compose (
    echo [ERROR] 缺少 config\.env.compose
    echo 請先執行: copy config\.env.compose.example config\.env.compose
    pause
    goto menu
)
docker compose --env-file config/.env.compose up -d postgres redis
if errorlevel 1 (
    echo Platform Engine 啟動失敗，請確認 Docker 已運行。
    pause
    goto menu
)
echo Platform Engine OK

call .engine7b\Scripts\activate.bat

echo.
echo [Step 2/3] Compute Engine - Seele...
start "Engine7B Compute Engine" cmd /k "python seele_v8_5.py --action deploy"
echo 等待 LLM 載入 VRAM (40s)...
timeout /t 40 /nobreak

echo.
echo [Step 3/3] Logic Engine - Vita API...
start "Engine7B Logic Engine" cmd /k "python -m uvicorn app.main:app_instance --host 127.0.0.1 --port 8000 --reload"

echo.
echo ========================================================
echo  三引擎啟動指令已全部發送
echo  健康檢查: http://127.0.0.1:8000/health/engines
echo  聊天介面: http://127.0.0.1:8000/
echo ========================================================
timeout /t 5 >nul
start "" "http://127.0.0.1:8000/health/engines"
goto menu

:kill_all
cls
echo 正在終止 Compute / Logic Engine 程序 (python.exe)...
taskkill /F /IM python.exe /T >nul 2>&1
echo 程序已關閉。Platform Engine (Docker) 仍運行中。
echo 若要停止 Docker: docker compose --env-file config/.env.compose stop postgres redis
pause
goto menu
