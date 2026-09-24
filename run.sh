#!/usr/bin/env bash
# 뼈대부터 짓는다 — macOS / Linux 실행
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo ".env 가 없습니다. cp .env.example .env 후 ANTHROPIC_API_KEY 를 넣으세요."
  exit 1
fi
python3 check_setup.py || exit 1
python3 -u app/server.py
