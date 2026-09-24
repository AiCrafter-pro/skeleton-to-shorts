@echo off
rem 뼈대부터 짓는다 — Windows 실행
cd /d "%~dp0"
if not exist ".env" (
  echo .env 가 없습니다. .env.example 을 .env 로 복사하고 ANTHROPIC_API_KEY 를 넣으세요.
  pause
  exit /b 1
)
python check_setup.py || (pause & exit /b 1)
start "" http://127.0.0.1:8932
python -u app\server.py
