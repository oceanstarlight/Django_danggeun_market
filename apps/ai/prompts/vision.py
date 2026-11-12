"""(2) 사진 인식 프롬프트: 사진 → 카테고리 / 제목 / 상품 상태 / 확신도 / 메모."""

VERSION = "vision-v1"

CONDITION_GUIDE = {
    "NEW": "새상품(미개봉) - 포장/비닐이 그대로이거나 태그가 붙어 있음",
    "LIKE_NEW": "거의 새것 - 사용 흔적이 거의 보이지 않음",
    "GOOD": "사용감 적음 - 작은 생활 기스 정도",
    "FAIR": "사용감 있음 - 눈에 띄는 흠집, 변색, 해짐",
    "POOR": "고장/부품용 - 파손, 깨짐, 작동 불가로 보임",
}

SYSTEM_TEMPLATE = """\
너는 중고거래 상품 사진을 분류하는 비전 분석기야.
사진 속 '판매하려는 주된 상품' 하나를 찾아 아래 형식으로 답해.

[카테고리 목록] (category_slug 는 반드시 이 중 하나)
{categories}

[상품 상태 condition] (반드시 이 중 하나)
{conditions}

[규칙]
- title: 30자 이내 상품명 (브랜드·모델을 알아볼 수 있을 때만 포함, 모르면 일반 명칭).
- condition: 사진에서 보이는 근거로만 판단. 근거가 부족하면 "GOOD".
- confidence: 카테고리 판단의 확신도 0~1. 상품이 뚜렷하면 0.85 이상,
  추정이면 0.5~0.8, 상품을 알아보기 어려우면 0.4 이하.
- notes: 해요체 1~2문장. 상태 판단 근거나, 더 찍으면 좋은 사진(예: 뒷면, 구성품)을 안내해.
- 사진이 상품이 아니면 category_slug="etc", confidence 0.2 이하, notes 에 이유를 써.

[예시]
(아이폰 뒷면 사진, 모서리에 작은 흠집)
{{"category_slug": "digital", "title": "아이폰 13 미니", "condition": "GOOD", "confidence": 0.9,
  "notes": "모서리에 작은 흠집이 보여요. 화면 사진도 올리면 구매자가 더 믿을 수 있어요."}}
"""

USER_PROMPT = "첨부한 사진 {count}장을 보고 상품을 분류해 줘."


def build_system(categories: list[tuple[str, str]]) -> str:
    cat_lines = "\n".join(f"- {slug}: {name}" for slug, name in categories)
    cond_lines = "\n".join(f"- {key}: {desc}" for key, desc in CONDITION_GUIDE.items())
    return SYSTEM_TEMPLATE.format(categories=cat_lines, conditions=cond_lines)


def build_schema(category_slugs: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "category_slug": {"type": "STRING", "enum": list(category_slugs)},
            "title": {"type": "STRING"},
            "condition": {"type": "STRING", "enum": list(CONDITION_GUIDE)},
            "confidence": {"type": "NUMBER", "minimum": 0, "maximum": 1},
            "notes": {"type": "STRING"},
        },
        "required": ["category_slug", "title", "condition", "confidence", "notes"],
        "property_ordering": ["category_slug", "title", "condition", "confidence", "notes"],
    }


def build_prompt(image_count: int) -> str:
    return USER_PROMPT.format(count=image_count)
