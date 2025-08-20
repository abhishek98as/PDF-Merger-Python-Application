@echo off
echo PDF Merger - Windows Build Script
echo ====================================

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Run the build script
echo Starting build process...
python build_exe.py

REM Check if build was successful
if %errorlevel% equ 0 (
    echo.
    echo Build completed successfully!
    echo The executable is located in the 'dist' folder.
    echo.
    echo Opening dist folder...
    explorer dist
) else (
    echo.
    echo Build failed! Check the error messages above.
)

pause
