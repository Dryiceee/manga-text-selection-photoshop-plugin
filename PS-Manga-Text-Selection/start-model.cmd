@echo off
chcp 65001 >nul
set PYTHONUTF8=1
"%~dp0..\Manga-Text-Segmentation\.venv\Scripts\python.exe" "%~dp0..\Manga-Text-Segmentation\launch.py" --no-browser
if errorlevel 1 pause
