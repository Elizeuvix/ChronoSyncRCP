@echo off
REM Inicia o servidor FastAPI sem hot-reload (estável para WebSockets)
cd /d "%~dp0\src\server\api"
uvicorn main:app --host 127.0.0.1 --port 8100
pause