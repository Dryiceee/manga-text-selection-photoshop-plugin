@echo off
chcp 65001 >nul
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" -Mode deploy
set "MANGA_DEPLOY_RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %MANGA_DEPLOY_RESULT%
