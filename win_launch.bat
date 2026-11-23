@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Starting Emotion Engine...
venv\Scripts\python.exe core.py
cmd /k