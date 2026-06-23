@echo off
REM Start backend (port 8001) and frontend (port 5175) in separate windows.
REM Run this from a regular cmd / Windows Terminal — both processes
REM will live for the lifetime of your terminal session.

setlocal
set ROOT=%~dp0

echo Starting backend on http://127.0.0.1:8001 ...
start "Hotel Contract Backend" cmd /k "cd /d %ROOT%backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level info"

echo Starting frontend on http://127.0.0.1:5175 ...
start "Hotel Contract Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev -- --port 5175 --host 127.0.0.1"

echo.
echo Two terminal windows have been launched.
echo   Backend:  http://127.0.0.1:8001/api/health
echo   Frontend: http://127.0.0.1:5175
echo.
echo Close the terminal windows to stop the services.
echo.
pause
