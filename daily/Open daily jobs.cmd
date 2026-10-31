@echo off
rem Double-click to open the daily jobs pages (starts the local page server if needed).
cd /d "%~dp0.."
start "" /b pythonw daily\server.py
timeout /t 2 /nobreak >nul
start "" "http://localhost:8765/"
