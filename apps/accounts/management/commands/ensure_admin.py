"""관리자 계정 보장 (배포용).

환경 변수가 있을 때만 동작한다. 없으면 아무것도 하지 않는다.
    DJANGO_SUPERUSER_USERNAME  관리자 아이디 (필수)
    DJANGO_SUPERUSER_PASSWORD  비밀번호 (필수)
    DJANGO_SUPERUSER_EMAIL     이메일 (선택)

- 계정이 없으면 관리자 계정을 만든다.
- 이미 있으면 비밀번호를 바꾸고 관리자 권한(is_staff/is_superuser)을 켠다.

Render 무료 플랜은 Shell 이 없어서 build.sh 에서 실행한다.
비밀번호를 바꾼 뒤에는 DJANGO_SUPERUSER_PASSWORD 를 지워 두는 것을 권장한다.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.services import ensure_profile


class Command(BaseCommand):
    help = "환경 변수로 관리자 계정을 만들거나 비밀번호를 재설정해요."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()

        if not username and not password:
            self.stdout.write("ensure_admin: 환경 변수가 없어서 건너뛰어요.")
            return
        if not username or not password:
            raise CommandError(
                "DJANGO_SUPERUSER_USERNAME 과 DJANGO_SUPERUSER_PASSWORD 를 둘 다 설정해 주세요."
            )

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError("비밀번호가 너무 약해요: " + " ".join(exc.messages))

        with transaction.atomic():
            created = user is None
            if created:
                user = User(username=username)
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            if email:
                user.email = email
            user.set_password(password)
            user.save()
            ensure_profile(user)

        if created:
            msg = f"ensure_admin: 관리자 '{username}' 계정을 만들었어요."
        else:
            msg = f"ensure_admin: '{username}' 계정의 비밀번호를 재설정하고 관리자 권한을 켰어요."
        self.stdout.write(self.style.SUCCESS(msg))
