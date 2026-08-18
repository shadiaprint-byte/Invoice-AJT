@echo off
title QuickInvoice
echo ============================================
echo   QuickInvoice - Invoicing Software
echo ============================================
echo.
echo Starting the application...
echo.

REM Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed.
    echo Please install Python 3 from: https://www.python.org/downloads/
    echo During installation, CHECK the box "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

python server.py

echo.
echo The application has stopped.
pause
