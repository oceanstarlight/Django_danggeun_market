"""테스트용 간단 팩토리."""

import io
import itertools

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Profile, Region
from apps.products.models import Category, Product

User = get_user_model()
_seq = itertools.count(1)


def make_user(username=None, nickname=None, region=None, password="pass-1234-word", **profile_kwargs):
    n = next(_seq)
    username = username or f"user{n}"
    user = User.objects.create_user(username=username, password=password)
    Profile.objects.create(
        user=user,
        nickname=nickname or f"이웃{n}",
        region=region if region is not None else Region.objects.first(),
        **profile_kwargs,
    )
    return user


def make_product(seller, **kwargs):
    n = next(_seq)
    defaults = {
        "category": Category.objects.first(),
        "region": Region.objects.first(),
        "title": f"테스트 상품 {n}",
        "content": "상품 설명이에요.",
        "price": 10000,
    }
    defaults.update(kwargs)
    return Product.objects.create(seller=seller, **defaults)


def png_file(name="avatar.png", size=(8, 8)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (13, 148, 136)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")
