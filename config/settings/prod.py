"""운영 설정 (Render + Supabase)."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = os.getenv("DEBUG", "0") == "1"

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("운영 환경에는 SECRET_KEY 환경변수가 필요해요.")

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "django-danggeun-market-vwl5.onrender.com",
]
render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)

CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS if host not in ("127.0.0.1", "localhost")
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT"),
        # 연결 재사용(매 요청 TLS 재연결 비용 절약).
        # Supabase 풀러는 한동안 쓰지 않은 연결을 서버 쪽에서 끊는다. 재사용 전에 연결이
        # 살아 있는지 확인하지 않으면, 30초마다 polling 하는 알림 배지 같은 요청이
        # 끊긴 연결을 집어 들어 500 이 난다 → CONN_HEALTH_CHECKS 로 재사용 전 확인.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        # 풀러(transaction 모드)에서는 서버측 커서(.iterator())가 트랜잭션 사이에 유지되지 않는다.
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": {"sslmode": "require", "connect_timeout": 10},
    }
}

# 운영 이미지는 Supabase Storage
USE_SUPABASE_STORAGE = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Render 는 프록시 뒤에서 HTTPS 를 처리한다
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
