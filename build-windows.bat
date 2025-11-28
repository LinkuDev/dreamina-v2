@echo off
chcp 65001 >nul
title Build Jimeng Generator - Windows Release

echo ==================================
echo   Building Windows Release
echo ==================================

cd /d "%~dp0"

:: Create release folder
if exist "release\windows" rmdir /s /q "release\windows"
mkdir "release\windows"

echo.
echo [1/4] Building Node.js server...
call npm run build
if errorlevel 1 (
    echo ERROR: npm build failed!
    pause
    exit /b 1
)

echo.
echo [2/4] Packaging Node.js to exe with pkg...
call npx pkg dist/index.js -t node18-win-x64 -o release\windows\dreamina-server.exe
if errorlevel 1 (
    echo ERROR: pkg failed!
    pause
    exit /b 1
)

echo.
echo [3/4] Installing PyInstaller...
pip install pyinstaller requests

echo.
echo [4/4] Packaging Python GUI to exe...
pyinstaller --onefile --windowed --name "DreaminaGUI" --icon=NONE main.py
if errorlevel 1 (
    echo ERROR: PyInstaller failed!
    pause
    exit /b 1
)

:: Copy files to release
copy "dist\DreaminaGUI.exe" "release\windows\"
mkdir "release\windows\prompt"
mkdir "release\windows\session"
mkdir "release\windows\outputs"
mkdir "release\windows\configs"
xcopy /E /I "configs" "release\windows\configs"

:: Copy sample files if exist
copy "prompt\*.txt" "release\windows\prompt\" 2>nul
copy "session\*.txt" "release\windows\session\" 2>nul

:: Create start script
echo @echo off > "release\windows\start.bat"
echo cd /d "%%~dp0" >> "release\windows\start.bat"
echo start /b dreamina-server.exe >> "release\windows\start.bat"
echo timeout /t 3 /nobreak ^>nul >> "release\windows\start.bat"
echo DreaminaGUI.exe >> "release\windows\start.bat"
echo taskkill /f /im dreamina-server.exe ^>nul 2^>^&1 >> "release\windows\start.bat"

:: Create README
echo # Dreamina Image Generator > "release\windows\README.txt"
echo. >> "release\windows\README.txt"
echo ## How to use: >> "release\windows\README.txt"
echo 1. Add session IDs to session\session.txt (one per line) >> "release\windows\README.txt"
echo 2. Add prompts to prompt\prompt.txt (one per line) >> "release\windows\README.txt"
echo 3. Double-click start.bat >> "release\windows\README.txt"
echo 4. Images will be saved in outputs\ folder >> "release\windows\README.txt"

echo.
echo ==================================
echo   Build Complete!
echo ==================================
echo.
echo Release folder: release\windows\
echo.
dir "release\windows"
echo.
pause
