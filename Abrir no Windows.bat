@echo off
cd /d "%~dp0"
py -3 iniciar.py
if errorlevel 1 pause
