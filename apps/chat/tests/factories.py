"""채팅 테스트용 간단한 데이터 생성 헬퍼."""

import itertools

from django.contrib.auth import get_user_model

from apps.accounts.models import Profile, Region
from apps.products.models import Category, Product

User = get_user_model()
_seq = itertools.count(1)


def make_user(nickname=None, password="pass-1234-word"):
    n = next(_seq)
    user = User.objects.create_user(username=f"chatuser{n}", password=password)
    Profile.objects.create(user=user, nickname=nickname or f"채팅이웃{n}", region=Region.objects.first())
    return user


def make_product(seller, **kwargs):
    defaults = {
        "category": Category.objects.first(),
        "region": Region.objects.first(),
        "title": "아이패드 미니 6세대",
        "content": "깨끗하게 썼어요.",
        "price": 450000,
    }
    defaults.update(kwargs)
    return Product.objects.create(seller=seller, **defaults)
