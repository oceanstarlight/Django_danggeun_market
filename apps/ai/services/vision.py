"""(2) 사진 인식: 사진 → {category_slug, title, condition, confidence, notes}.

카테고리는 DB 의 Category 목록 안에서만, 상태는 Product.Condition 값 안에서만 고르게 한다.
"""

from __future__ import annotations

from apps.ai import client as ai_client
from apps.ai.cache import AIResult, cached_call
from apps.ai.images import AIInputError
from apps.ai.models import AIFeature
from apps.ai.prompts import vision as P

FALLBACK_CATEGORY = "etc"


def _categories():
    from apps.products.models import Category

    return list(Category.objects.order_by("order", "id").values_list("pk", "slug", "name"))


def normalize(data: dict, categories) -> dict:
    """모델 출력 검증 + 화면용 필드(category_id/name, condition_label) 보강."""
    from apps.products.models import Product

    by_slug = {slug: (pk, name) for pk, slug, name in categories}
    slug = str(data.get("category_slug") or "").strip().lower()
    if slug not in by_slug:
        slug = FALLBACK_CATEGORY if FALLBACK_CATEGORY in by_slug else next(iter(by_slug), "")
    condition = str(data.get("condition") or "").strip().upper()
    if condition not in Product.Condition.values:
        condition = Product.Condition.GOOD
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = round(min(max(confidence, 0.0), 1.0), 2)
    pk, name = by_slug.get(slug, (None, ""))
    return {
        "category_slug": slug,
        "category_id": pk,
        "category_name": name,
        "title": " ".join(str(data.get("title") or "").split())[:100],
        "condition": condition,
        "condition_label": Product.Condition(condition).label,
        "confidence": confidence,
        "confidence_percent": int(round(confidence * 100)),
        "notes": str(data.get("notes") or "").strip()[:300],
    }


def recognize_product(images: list[tuple[bytes, str]], *, user=None, regenerate: bool = False) -> AIResult:
    """사진 분석. 반환: AIResult(data=normalize 결과, cached, usage)."""
    images = list(images)[:2]
    if not images:
        raise AIInputError("사진을 1장 이상 올려 주세요.")
    categories = _categories()
    system = P.build_system([(slug, name) for _pk, slug, name in categories])
    schema = P.build_schema([slug for _pk, slug, _name in categories])
    prompt = P.build_prompt(len(images))

    def call():
        data, usage = ai_client.get_client().generate_json(
            prompt, images=images, schema=schema, temperature=0.2, system=system
        )
        return data, usage

    # 캐시에는 원본 응답을 저장하고, 카테고리 pk 등은 매번 현재 DB 기준으로 보강
    parts = [P.VERSION, system, prompt, *[data for data, _mime in images]]
    result = cached_call(AIFeature.VISION, parts, call, user=user, refresh=regenerate)
    result.data = normalize(result.data, categories)
    return result
