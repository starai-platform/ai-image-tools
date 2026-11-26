@echo off
chcp 65001 >nul 2>&1
title AI Image Reconstruction - Web UI

cd /d "%~dp0"

echo.
echo  ==========================================
echo   AI Image Reconstruction Tool - Web UI
echo  ==========================================
echo.

:: Check .env.local
if not exist ".env.local" (
    echo  ERROR: .env.local not found.
    echo  Please copy .env.local.example to .env.local
    echo  and fill in your OPENAI_API_KEY and IMG2IMG_BASE_URL
    echo.
    pause
    exit /b 1
)

:: Load .env.local - parse key=value lines, skip # comments
for /f "tokens=1,* delims==" %%A in ('findstr /v "^#" .env.local') do (
    if not "%%A"=="" set "%%A=%%B"
)

:: Validate keys
if "%OPENAI_API_KEY%"=="" (
    echo  ERROR: OPENAI_API_KEY is not set in .env.local
    pause
    exit /b 1
)
if "%IMG2IMG_BASE_URL%"=="" (
    echo  ERROR: IMG2IMG_BASE_URL is not set in .env.local
    pause
    exit /b 1
)

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

:: Install dependencies
echo  Checking dependencies...
pip install flask flask-cors pillow openai requests -q 2>nul

echo.
echo  Starting Flask server...
echo  Press CTRL+C to stop.
echo.

:: Open the address actually bound by this instance.
python app_flask_pro_english.py --open-browser

echo.
pause
