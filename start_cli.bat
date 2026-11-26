@echo off
chcp 65001 >nul 2>&1
title AI Image Reconstruction - CLI

cd /d "%~dp0"

echo.
echo  ==========================================
echo   AI Image Reconstruction Tool - CLI
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
pip install pillow openai requests -q 2>nul

echo.

:: Prompt for settings
set "INPUT_DIR=raw_images"
set "OUTPUT_DIR=output_main_webp"
set "MAX_WORKERS=3"

set /p "INPUT_DIR=Input folder  [default: raw_images]: "
if "%INPUT_DIR%"=="" set "INPUT_DIR=raw_images"

set /p "OUTPUT_DIR=Output folder [default: output_main_webp]: "
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=output_main_webp"

set /p "MAX_WORKERS=Concurrent workers [default: 3]: "
if "%MAX_WORKERS%"=="" set "MAX_WORKERS=3"

echo.
echo  ------------------------------------------
echo   Input  : %INPUT_DIR%
echo   Output : %OUTPUT_DIR%
echo   Workers: %MAX_WORKERS%
echo  ------------------------------------------
echo.

python batch_product_main_cli.py ^
    --input "%INPUT_DIR%" ^
    --output "%OUTPUT_DIR%" ^
    --max-workers %MAX_WORKERS%

echo.
echo  Done. Results saved to: %OUTPUT_DIR%
echo.
pause
