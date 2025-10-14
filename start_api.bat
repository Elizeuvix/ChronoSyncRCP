@echo off
setlocal
REM Inicia o servidor FastAPI com Uvicorn
REM Vai para a pasta da API
cd /d "%~dp0\src\server\api"

REM Garante que 'src\server' esteja no PYTHONPATH para imports (common, ws)
set "PYTHONPATH=%CD%\..;%PYTHONPATH%"

REM ================== ChronoSyncRCP Admin/API Config ==================
REM Defina o token de administrador para autorizar os endpoints /admin (cabeçalho X-Admin-Token)
REM IMPORTANTE: Troque o valor abaixo por um segredo forte no seu ambiente local.
REM Você também pode removê-lo daqui e definir ADMIN_TOKEN como variável de ambiente do Windows.
set "ADMIN_TOKEN=CHRONO351SYNC195@admin"
REM (Dica) Não registramos o valor do token no console por segurança.
REM ====================================================================

REM Executa uvicorn (fallback para python -m caso uvicorn não esteja no PATH)
where uvicorn >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
		python -m uvicorn main:app --host 127.0.0.1 --port 8100
) else (
		uvicorn main:app --host 127.0.0.1 --port 8100
)

pause
endlocal