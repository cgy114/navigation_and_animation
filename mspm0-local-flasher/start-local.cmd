@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 18+ and run this file again.
  pause
  exit /b 1
)
start "MSPM0 local server" cmd /k "node server.js"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
echo Browser opened. Keep the MSPM0 local server window open while using the tool.
endlocal
