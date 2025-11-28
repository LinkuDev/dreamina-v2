# Build Jimeng Generator - Windows Release (PowerShell)

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "  Building Windows Release" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

Set-Location $PSScriptRoot

# Create release folder
$releaseDir = "release\windows"
if (Test-Path $releaseDir) { Remove-Item -Recurse -Force $releaseDir }
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
New-Item -ItemType Directory -Force -Path "$releaseDir\prompt" | Out-Null
New-Item -ItemType Directory -Force -Path "$releaseDir\session" | Out-Null
New-Item -ItemType Directory -Force -Path "$releaseDir\outputs" | Out-Null
New-Item -ItemType Directory -Force -Path "$releaseDir\configs" | Out-Null

# Step 1: Build Node.js
Write-Host "`n[1/4] Building Node.js server..." -ForegroundColor Yellow
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: npm build failed!" -ForegroundColor Red
    exit 1
}

# Step 2: Package with pkg
Write-Host "`n[2/4] Packaging Node.js to exe..." -ForegroundColor Yellow
npx pkg dist/index.cjs -t node18-win-x64 -o "$releaseDir\dreamina-server.exe" -C
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pkg failed!" -ForegroundColor Red
    exit 1
}

# Step 3: Install PyInstaller
Write-Host "`n[3/4] Installing PyInstaller..." -ForegroundColor Yellow
pip install pyinstaller requests --quiet

# Step 4: Package Python GUI
Write-Host "`n[4/4] Packaging Python GUI to exe..." -ForegroundColor Yellow
pyinstaller --onefile --windowed --name "DreaminaGUI" --clean main.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller failed!" -ForegroundColor Red
    exit 1
}

# Copy files
Copy-Item "dist\DreaminaGUI.exe" "$releaseDir\"
Copy-Item "package.json" "$releaseDir\"
Copy-Item -Recurse "configs\*" "$releaseDir\configs\" -ErrorAction SilentlyContinue
Copy-Item "prompt\*.txt" "$releaseDir\prompt\" -ErrorAction SilentlyContinue
Copy-Item "session\*.txt" "$releaseDir\session\" -ErrorAction SilentlyContinue

# Create start.bat
$startBat = @"
@echo off
cd /d "%~dp0"
start /b dreamina-server.exe
timeout /t 3 /nobreak >nul
DreaminaGUI.exe
taskkill /f /im dreamina-server.exe >nul 2>&1
"@
$startBat | Out-File -FilePath "$releaseDir\start.bat" -Encoding ASCII

# Create README
$readme = @"
# Dreamina Image Generator

## How to use:
1. Add session IDs to session\session.txt (one per line)
2. Add prompts to prompt\prompt.txt (one per line)
3. Double-click start.bat
4. Images will be saved in outputs\ folder

## Files:
- dreamina-server.exe : API server (runs on port 5100)
- DreaminaGUI.exe     : GUI application
- start.bat           : Launches both server and GUI
"@
$readme | Out-File -FilePath "$releaseDir\README.txt" -Encoding UTF8

Write-Host "`n==================================" -ForegroundColor Green
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host "`nRelease folder: $releaseDir" -ForegroundColor Cyan
Get-ChildItem $releaseDir | Format-Table Name, Length -AutoSize

Write-Host "`nPress any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
