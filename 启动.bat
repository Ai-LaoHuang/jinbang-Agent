@echo off
cd /d "%~dp0"
echo Starting...
py -3 server.py || python server.py
pause
