"""AI 테스트 공용 도우미 (GeminiClient 는 항상 mock)."""

import io
from contextlib import contextmanager
from unittest import mock

from django.contrib.auth import get_user_model
from PIL import Image

from apps.ai.client import AIUsage
from apps.products.models import Category, Product

User = get_user_model()


def make_png_bytes(color=(200, 30, 30), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def make_upload(name="photo.png", color=(200, 30, 30)):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, make_png_bytes(color), content_type="image/png")


def usage(prompt=120, output=80, latency=900):
    return AIUsage(model="gemini-test", prompt_tokens=prompt, output_tokens=output,
                   total_tokens=prompt + output, latency_ms=latency)


@contextmanager
def fake_gemini(*responses, side_effect=None):
    """apps.ai.client.get_client 를 mock. responses 는 차례로 반환할 dict 들."""
    client = mock.Mock()
    if side_effect is not None:
        client.generate_json.side_effect = side_effect
    else:
        client.generate_json.side_effect = [(r, usage()) for r in responses]
    with mock.patch("apps.ai.client.get_client", return_value=client):
        yield client


class AIDataMixin:
    """사용자 · 상품 기본 데이터."""

    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user("seller", password="pw-1234!!")
        cls.buyer = User.objects.create_user("buyer", password="pw-1234!!")
        cls.stranger = User.objects.create_user("stranger", password="pw-1234!!")
        cls.staff = User.objects.create_user("staff", password="pw-1234!!", is_staff=True)
        cls.digital = Category.objects.get(slug="digital")

    def make_product(self, **kwargs):
        defaults = {
            "seller": self.seller,
            "category": self.digital,
            "title": "아이패드 에어 5세대 64GB",
            "content": "1년 사용했어요. 생활 기스 조금 있고 배터리 좋아요. 직거래 원해요.",
            "price": 450000,
            "negotiable": True,
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)
