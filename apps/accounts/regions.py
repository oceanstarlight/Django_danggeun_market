"""동네(Region) 3단 선택: 시/도 → 시/군/구 → 읍/면/동.

- 목록 조회(*_choices): 새로 고를 수 있는 건 행정동 코드가 있는 행(code 有)뿐이다.
  예전 시드에만 있던 행(code 無)은 지금 고른 값(current)일 때만 끼워 넣어 그대로 보여준다.
- 시/군/구 이름은 시/도마다 겹치므로(동구·서구·중구 …) 항상 시/도와 함께 조회한다.
- 정렬은 가나다순 + 숫자는 크기순('상계2동' < '상계10동'). DB 콜레이션과 상관없이 같은 결과가 나오게
  파이썬에서 정렬한다 (한 번에 많아야 수십 개).
- 조회는 (sido, sigungu, dong) 유니크 인덱스의 앞부분을 그대로 쓴다.

products 앱도 쓰므로 accounts.selectors(상품 모델을 import) 와 분리해 둔다.
"""

import re
from dataclasses import dataclass, field

from django.urls import reverse

from .models import Region

LEVELS = ("sido", "sigungu", "dong")
LEVEL_LABELS = {"sido": "시/도", "sigungu": "시/군/구", "dong": "읍/면/동"}
_NUM_RE = re.compile(r"(\d+)")


def korean_sort_key(value):
    """가나다순, 숫자는 크기순."""
    return [int(part) if part.isdigit() else part for part in _NUM_RE.split(value or "")]


def _official():
    return Region.objects.filter(code__isnull=False)


def sido_choices(current=None):
    """시/도 이름 목록."""
    names = set(_official().order_by().values_list("sido", flat=True).distinct())
    if current is not None:
        names.add(current.sido)
    return sorted(names, key=korean_sort_key)


def sigungu_choices(sido, current=None):
    """해당 시/도의 시/군/구 이름 목록 (시/도가 비면 [])."""
    if not sido:
        return []
    names = set(_official().filter(sido=sido).order_by().values_list("sigungu", flat=True).distinct())
    if current is not None and current.sido == sido:
        names.add(current.sigungu)
    return sorted(names, key=korean_sort_key)


def dong_choices(sido, sigungu, current=None):
    """해당 시/도 + 시/군/구의 [(pk, 읍/면/동 이름), ...]."""
    if not (sido and sigungu):
        return []
    items = dict(_official().filter(sido=sido, sigungu=sigungu).order_by().values_list("pk", "dong"))
    if current is not None and (current.sido, current.sigungu) == (sido, sigungu):
        items[current.pk] = current.dong
    return sorted(items.items(), key=lambda item: korean_sort_key(item[1]))


def sido_exists(sido):
    return bool(sido) and Region.objects.filter(sido=sido).exists()


def sigungu_exists(sido, sigungu):
    return bool(sido and sigungu) and Region.objects.filter(sido=sido, sigungu=sigungu).exists()


def region_by_pk(value):
    """'123' / 123 / Region → Region 또는 None."""
    if isinstance(value, Region):
        return value
    value = str(value or "").strip()
    if not value.isdigit():
        return None
    return Region.objects.filter(pk=int(value)).first()


# ───────── 템플릿(components/region_select.html) 컨텍스트 ─────────
@dataclass
class RegionLevel:
    level: str
    id: str
    name: str
    label: str
    placeholder: str
    empty_value: str = ""
    options: list = field(default_factory=list)  # [(value, label, selected)]
    disabled: bool = False
    hx_vals: str = ""  # 다음 단계를 불러올 때 보낼 값 (JSON)
    hx_target: str = ""
    hx_include: str = ""


def placeholders(mode, sido="", sigungu=""):
    """단계별 첫 옵션 문구. filter 모드는 '전체'를 뜻한다."""
    if mode == "filter":
        return {
            "sido": "전체 지역",
            "sigungu": f"{sido} 전체" if sido else "시/군/구",
            "dong": f"{sigungu} 전체" if sigungu else "읍/면/동",
        }
    return {"sido": "시/도 선택", "sigungu": "시/군/구 선택", "dong": "읍/면/동 선택"}


def build_select_context(
    *,
    id_prefix,
    names,
    sido="",
    sigungu="",
    region=None,
    mode="form",
    attrs=None,
    dong_empty_value="",
    legend="",
):
    """3단 select 렌더 컨텍스트.

    names: {"sido": ..., "sigungu": ..., "dong": ...} — 마지막(dong) 이름이 폼 필드 이름이고 값은 Region pk.
    region 이 있으면 sido/sigungu 는 region 기준으로 맞춘다. (서버에서 옵션까지 다 그려서 왕복이 없음)
    mode: "form"(가입·프로필·상품 폼, HTMX 로 다음 단계를 불러옴) | "filter"(목록 필터, 바꾸면 폼이 바로 제출됨)
    """
    if region is not None:
        sido, sigungu = region.sido, region.sigungu
    current = region
    sidos = sido_choices(current)
    if sido not in sidos:
        sido, sigungu = "", ""
    sigungus = sigungu_choices(sido, current)
    if sigungu not in sigungus:
        sigungu = ""
    dongs = dong_choices(sido, sigungu, current)

    attrs = dict(attrs or {})
    extra_class = attrs.pop("class", "")
    attrs.pop("id", None)
    text = placeholders(mode, sido, sigungu)
    ids = {"sido": f"{id_prefix}_sido", "sigungu": f"{id_prefix}_sigungu", "dong": id_prefix}
    use_htmx = mode == "form"

    levels = [
        RegionLevel(
            level="sido",
            id=ids["sido"],
            name=names["sido"],
            label=LEVEL_LABELS["sido"],
            placeholder=text["sido"],
            options=[(name, name, name == sido) for name in sidos],
            hx_vals='{"level": "sigungu"}' if use_htmx else "",
            hx_target=f"#{ids['sigungu']}" if use_htmx else "",
        ),
        RegionLevel(
            level="sigungu",
            id=ids["sigungu"],
            name=names["sigungu"],
            label=LEVEL_LABELS["sigungu"],
            placeholder=text["sigungu"],
            options=[(name, name, name == sigungu) for name in sigungus],
            disabled=not sido,
            hx_vals='{"level": "dong"}' if use_htmx else "",
            hx_target=f"#{ids['dong']}" if use_htmx else "",
            hx_include=f"#{ids['sido']}" if use_htmx else "",
        ),
        RegionLevel(
            level="dong",
            id=ids["dong"],
            name=names["dong"],
            label=LEVEL_LABELS["dong"],
            placeholder=text["dong"],
            empty_value=dong_empty_value,
            options=[(str(pk), name, region is not None and pk == region.pk) for pk, name in dongs],
            disabled=not sigungu,
        ),
    ]
    return {
        "levels": levels,
        "mode": mode,
        "legend": legend,
        "extra_class": extra_class,
        "attrs": attrs,
        "options_url": reverse("accounts:region_options") if use_htmx else "",
    }
