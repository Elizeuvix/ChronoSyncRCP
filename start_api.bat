@echo off
REM Inicia o servidor FastAPI com Uvicorn
cd /d "%~dp0\src\server\api"
uvicorn main:app --reload
pause