#!/usr/bin/env bash
# Render 빌드 스크립트 (Tailwind 는 커밋된 static/css/app.css 를 사용하므로 npm 불필요)
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# 시작 명령(Render): gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker
