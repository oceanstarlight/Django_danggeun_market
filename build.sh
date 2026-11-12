#!/usr/bin/env bash
# Render 빌드 스크립트 (Tailwind 는 커밋된 static/css/app.css 를 사용하므로 npm 불필요)
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
# DJANGO_SUPERUSER_USERNAME/PASSWORD 가 있을 때만 관리자 계정 생성·비밀번호 재설정 (없으면 건너뜀)
python manage.py ensure_admin

# 시작 명령(Render): gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker
