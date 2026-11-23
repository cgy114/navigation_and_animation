@echo off
setlocal
python -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
if errorlevel 1 (
    py -3 "%~dp0server.py" --open
) else (
    python "%~dp0server.py" --open
)
if errorlevel 1 pause
