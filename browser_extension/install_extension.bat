@echo off
title DeepX Vision Downloader - Chrome/Edge Extension Installer
echo ================================================================
echo    DeepX Vision Downloader - Browser Extension Setup
echo ================================================================
echo.
echo [1] Copying extension files to LocalAppData...
set TARGET_DIR=%LOCALAPPDATA%\DeepX Vision\browser_extension
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
xcopy /E /I /Y "%~dp0*" "%TARGET_DIR%\" >nul

echo [2] Registering Native Messaging Host for Google Chrome & Edge...
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.deepx.downloader" /ve /t REG_SZ /d "%TARGET_DIR%\manifest_native.json" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.deepx.downloader" /ve /t REG_SZ /d "%TARGET_DIR%\manifest_native.json" /f >nul 2>&1

echo.
echo ================================================================
echo    INSTALLATION STEPS:
echo ================================================================
echo 1. Open Google Chrome or Microsoft Edge.
echo 2. Go to: chrome://extensions/  or  edge://extensions/
echo 3. Enable "Developer mode" (top right toggle).
echo 4. Click "Load unpacked" (top left button).
echo 5. Select this folder:
echo    "%TARGET_DIR%"
echo ================================================================
echo.
pause
