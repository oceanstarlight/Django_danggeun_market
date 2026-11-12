"""카테고리(Category) 기본 데이터 시드."""

from django.db import migrations

CATEGORIES = [
    ("digital", "디지털기기", "📱"),
    ("appliance", "생활가전", "🔌"),
    ("furniture", "가구/인테리어", "🛋️"),
    ("kitchen", "생활/주방", "🍳"),
    ("kids", "유아동", "🧸"),
    ("women", "여성의류", "👗"),
    ("men", "남성패션/잡화", "👟"),
    ("beauty", "뷰티/미용", "💄"),
    ("sports", "스포츠/레저", "⚽"),
    ("hobby", "취미/게임/음반", "🎮"),
    ("books", "도서", "📚"),
    ("ticket", "티켓/교환권", "🎫"),
    ("pet", "반려동물용품", "🐶"),
    ("plant", "식물", "🪴"),
    ("etc", "기타 중고물품", "📦"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    for order, (slug, name, icon) in enumerate(CATEGORIES, start=1):
        Category.objects.update_or_create(slug=slug, defaults={"name": name, "icon": icon, "order": order})


def unseed(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    Category.objects.filter(slug__in=[slug for slug, _, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("products", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
