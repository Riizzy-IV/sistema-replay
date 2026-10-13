@echo off
rem Inicia o servidor de replay. Na primeira execução cria o ambiente Python e instala as dependências.
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist config.json (
  echo Falta o config.json - copie config.example.json para config.json e preencha.
  pause
  exit /b 1
)
:loop
.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000
echo Servidor caiu, reiniciando em 5s...
timeout /t 5 /nobreak >nul
goto loop
