"""개발/테스트 설정.

주의: 이 컨테이너에는 운영 DB/Storage 접속정보가 환경변수로 들어 있을 수 있다.
dev 는 이를 무시하고 항상 SQLite + 로컬 MEDIA_ROOT 를 쓴다.
(USE_POSTGRES=1 / USE_SUPABASE_STORAGE=1 일 때만 예외)
"""

import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env_bool

DEBUG = True
SECRET_KEY = os.getenv("DJANGO_DEV_SECRET_KEY", "dev-only-insecure-secret-key-polymarket")
ALLOWED_HOSTS = ["*"]

if env_bool("USE_POSTGRES"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER"),
            "PASSWORD": os.getenv("DB_PASSWORD"),
            "HOST": os.getenv("DB_HOST"),
            "PORT": os.getenv("DB_PORT"),
            "OPTIONS": {"sslmode": "require", "connect_timeout": 10},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# 이미지: 기본은 로컬 저장
USE_SUPABASE_STORAGE = env_bool("USE_SUPABASE_STORAGE", False)
