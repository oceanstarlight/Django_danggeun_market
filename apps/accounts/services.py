"""accounts 쓰기 로직 (회원가입 · 프로필)."""

import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.core.storage import upload_image

from .models import Profile

logger = logging.getLogger(__name__)
User = get_user_model()

AVATAR_FOLDER = "avatars"


class AccountError(Exception):
    """사용자에게 보여줄 수 있는 계정 처리 오류."""


def register_user(*, username, password, nickname, name="", birth_date=None, phone=None, region=None):
    """User + Profile 을 함께 만든다. 중복(동시 가입 등)이면 AccountError."""
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password, first_name=name)
            Profile.objects.create(
                user=user,
                nickname=nickname,
                birth_date=birth_date,
                phone=phone or None,
                region=region,
            )
    except IntegrityError as exc:
        logger.info("회원가입 중복: %s", exc)
        raise AccountError("이미 사용 중인 아이디, 닉네임 또는 휴대폰 번호예요. 다시 확인해 주세요.") from exc
    return user


def _unique_nickname(base: str) -> str:
    base = (base or "이웃")[:16]
    candidate, n = base, 1
    while Profile.objects.filter(nickname__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def ensure_profile(user) -> Profile:
    """프로필이 없는 사용자(관리자 등)는 기본 프로필을 만들어 준다."""
    try:
        return user.profile
    except Profile.DoesNotExist:
        profile, _ = Profile.objects.get_or_create(
            user=user, defaults={"nickname": _unique_nickname(user.username)}
        )
        user.profile = profile
        return profile


def update_profile(profile: Profile, *, nickname, region, bio="", avatar_file=None, remove_avatar=False) -> Profile:
    """프로필을 수정한다. 아바타 업로드 실패 시 StorageError 를 그대로 올려요(저장 안 함)."""
    if avatar_file:
        # 업로드를 먼저 해서 실패하면 아무것도 바뀌지 않게
        profile.avatar_url = upload_image(avatar_file, AVATAR_FOLDER)
    elif remove_avatar:
        profile.avatar_url = ""
    profile.nickname = nickname
    profile.region = region
    profile.bio = bio
    try:
        with transaction.atomic():
            profile.save(update_fields=["nickname", "region", "bio", "avatar_url"])
    except IntegrityError as exc:
        raise AccountError("이미 사용 중인 닉네임이에요.") from exc
    return profile
