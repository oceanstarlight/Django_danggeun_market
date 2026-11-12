"""전국 행정동(3,559개)을 Region 에 넣는다.

데이터: apps/accounts/data/regions_hangjeongdong_20261001.csv
  - '#' 으로 시작하는 줄은 출처·라이선스 주석이라 건너뛴다.
  - 열: code,sido,sigungu,dong

동작 (운영 DB 에 0002 시드가 이미 들어가 있어도 안전하게):
  1. (sido, sigungu, dong) 이 같은 행이 있으면 code 만 채우고, 없으면 새로 만든다. (bulk)
  2. CSV 에 없는 예전 시드 행(예: '성수동1가', '부천시 중동')은
     - Region 을 가리키는 FK(Profile.region, Product.region 등, 마이그레이션 상태에서 자동으로 찾음)가
       하나라도 있으면 그대로 둔다. (code 는 비어 있음 → 새로 고르는 목록에는 안 나옴)
     - 아무도 안 쓰면 지운다.
  되돌리기(reverse)는 아무것도 하지 않는다. (0003 을 되돌리면 code 열만 사라짐)
SQLite / PostgreSQL 모두 같은 ORM 코드로 동작한다.
"""

import csv
from pathlib import Path

from django.db import migrations

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "regions_hangjeongdong_20261001.csv"
BATCH_SIZE = 500


def read_rows(path=CSV_PATH):
    """[(code, sido, sigungu, dong), ...] — 주석('#') 줄과 빈 줄은 건너뛴다."""
    with path.open(encoding="utf-8", newline="") as f:
        lines = (line for line in f if line.strip() and not line.lstrip().startswith("#"))
        reader = csv.DictReader(lines)
        return [
            (row["code"].strip(), row["sido"].strip(), row["sigungu"].strip(), row["dong"].strip())
            for row in reader
        ]


def referenced_region_ids(Region, using, candidate_ids):
    """candidate_ids 중 어떤 모델이든 FK/O2O/M2M 으로 가리키고 있는 Region id 집합."""
    referenced = set()
    if not candidate_ids:
        return referenced
    for rel in Region._meta.related_objects:
        model = rel.related_model
        name = rel.field.name
        qs = model._base_manager.using(using).filter(**{f"{name}__in": candidate_ids})
        referenced.update(qs.values_list(name, flat=True).distinct())
    referenced.discard(None)
    return referenced


def load_regions(apps, schema_editor):
    Region = apps.get_model("accounts", "Region")
    using = schema_editor.connection.alias
    manager = Region._base_manager.using(using)

    rows = read_rows()
    existing = {(r.sido, r.sigungu, r.dong): r for r in manager.all()}
    by_code = {r.code: r for r in existing.values() if r.code}

    to_create, to_update, freed = [], [], []
    for code, sido, sigungu, dong in rows:
        obj = existing.get((sido, sigungu, dong))
        holder = by_code.get(code)
        if holder is not None and holder is not obj:
            # 같은 코드를 다른 이름의 행이 들고 있으면(다시 돌릴 때 등) 먼저 비운다 → unique 충돌 방지
            holder.code = None
            freed.append(holder)
        if obj is None:
            to_create.append(Region(code=code, sido=sido, sigungu=sigungu, dong=dong))
        elif obj.code != code:
            obj.code = code
            to_update.append(obj)

    if freed:
        manager.bulk_update(freed, ["code"], batch_size=BATCH_SIZE)
    if to_update:
        manager.bulk_update(to_update, ["code"], batch_size=BATCH_SIZE)
    if to_create:
        manager.bulk_create(to_create, batch_size=BATCH_SIZE)

    # CSV 에 없는 예전 행 정리 (누가 쓰고 있으면 남긴다)
    csv_keys = {(sido, sigungu, dong) for _, sido, sigungu, dong in rows}
    legacy_ids = [r.pk for key, r in existing.items() if key not in csv_keys]
    keep = referenced_region_ids(Region, using, legacy_ids)
    deletable = [pk for pk in legacy_ids if pk not in keep]
    for start in range(0, len(deletable), BATCH_SIZE):
        manager.filter(pk__in=deletable[start : start + BATCH_SIZE]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_region_code")]

    operations = [migrations.RunPython(load_regions, migrations.RunPython.noop)]
