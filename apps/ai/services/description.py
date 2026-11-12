"""(1) 상품 설명 생성: 사진 1~2장 + 키워드(+카테고리) → {title, content, suggested_tags}."""

from __future__ import annotations

import re

from apps.ai import client as ai_client
from apps.ai.cache import AIResult, cached_call
from apps.ai.client import AIServiceError, MSG_INVALID
from apps.ai.images import AIInputError
from apps.ai.models import AIFeature
from apps.ai.prompts import description as P

MAX_KEYWORDS = 200
MAX_TITLE = 100
MAX_CONTENT = 2000


def _clean_tags(raw) -> list[str]:
    tags = []
    for tag in raw if isinstance(raw, list) else []:
        text = re.sub(r"[#\s]+", "", str(tag))[:20]
        if text and text not in tags:
            tags.append(text)
    return tags[:5]


def normalize(data: dict) -> dict:
    """모델 출력 검증/정리. 제목·본문이 비면 잘못된 응답으로 본다."""
    title = " ".join(str(data.get("title") or "").split())[:MAX_TITLE]
    content = str(data.get("content") or "").replace("\r\n", "\n").strip()
    content = re.sub(r"\n{3,}", "\n\n", content)[:MAX_CONTENT]
    if not title or not content:
        raise AIServiceError(MSG_INVALID, detail=f"description missing fields: {data!r}"[:300])
    return {"title": title, "content": content, "suggested_tags": _clean_tags(data.get("suggested_tags"))}


def generate_description(images: list[tuple[bytes, str]], keywords: str = "", category=None, *, user=None,
                         regenerate: bool = False) -> AIResult:
    """판매글 초안 생성. images 는 apps.ai.images.prepare_uploaded_images 결과.

    반환: AIResult(data={title, content, suggested_tags}, cached, usage)
    """
    keywords = " ".join((keywords or "").split())
    if len(keywords) > MAX_KEYWORDS:
        raise AIInputError(f"키워드는 {MAX_KEYWORDS}자까지 입력할 수 있어요.")
    if not images and not keywords:
        raise AIInputError("사진을 올리거나 키워드를 입력해 주세요.")
    images = list(images)[:2]
    category_name = getattr(category, "name", None)
    prompt = P.build_prompt(keywords=keywords, category_name=category_name, image_count=len(images))
    # '다시 생성'은 조금 더 다양하게
    temperature = 0.9 if regenerate else 0.5

    def call():
        data, usage = ai_client.get_client().generate_json(
            prompt, images=images, schema=P.SCHEMA, temperature=temperature, system=P.SYSTEM
        )
        return normalize(data), usage

    parts = [P.VERSION, P.SYSTEM, prompt, *[data for data, _mime in images]]
    return cached_call(AIFeature.DESCRIPTION, parts, call, user=user, refresh=regenerate)
