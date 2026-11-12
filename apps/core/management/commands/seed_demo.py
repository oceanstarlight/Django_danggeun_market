"""데모 데이터 생성 (개발 전용).

    python manage.py seed_demo            # 데모 데이터가 없으면 생성
    python manage.py seed_demo --reset    # 기존 데모 데이터를 지우고 다시 생성
    python manage.py seed_demo --with-ai  # 사기 탐지에 실제 Gemini 판단까지 사용

데모 계정(비밀번호 공통 demo1234!):
    demo_minji(민지네) · demo_junho(준호아빠) · demo_seoyeon(서연이네책방) · demo_dohyun(도현) · demo_quick(급처분해요)

상품 이미지는 PIL 로 로컬에서 그려서 core.storage.upload_image 로 저장한다.
쓰기는 모두 각 앱 서비스 함수를 거치므로 알림/매너온도/사기 분석도 실제 흐름과 똑같이 생긴다.
"""

import io
import math
import os
import random
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile, Region
from apps.accounts.services import register_user
from apps.chat.models import ChatMessage, ChatRoom
from apps.chat.services import get_or_create_room, send_message
from apps.moderation.models import Report
from apps.moderation.services import create_report
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.products.models import Category, Product, RecentView
from apps.products.services import create_product, record_view, toggle_wishlist, update_product
from apps.trades.models import Review
from apps.trades.services import complete_trade, create_review

User = get_user_model()

USERNAME_PREFIX = "demo_"
PASSWORD = "demo1234!"

# (key, 닉네임, 이름, 생년월일, 휴대폰, (시도, 시군구, 동), 소개, 시작 매너온도)
USERS = [
    ("minji", "민지네", "김민지", "1996-04-12", "010-5100-0001", ("서울특별시", "마포구", "서교동"),
     "합정·망원 근처에서 거래해요. 깨끗하게 쓴 물건만 올려요.", "38.4"),
    ("junho", "준호아빠", "이준호", "1988-09-03", "010-5100-0002", ("서울특별시", "마포구", "합정동"),
     "아이 물건 정리하고 있어요. 주말 직거래를 좋아해요.", "41.2"),
    ("seoyeon", "서연이네책방", "박서연", "1999-01-27", "010-5100-0003", ("서울특별시", "마포구", "망원동"),
     "책이랑 취미용품을 아껴 써요. 문의는 채팅으로 편하게 주세요.", "37.1"),
    ("dohyun", "도현", "최도현", "1993-11-18", "010-5100-0004", ("경기도", "성남시 분당구", "정자동"),
     "판교 출퇴근길에 거래 가능해요.", "36.8"),
    ("quick", "급처분해요", "", None, "010-5100-0005", ("서울특별시", "마포구", "서교동"),
     "", "36.5"),
]

# (판매자, 카테고리 slug, 제목, 가격, 가격제안, 상태(condition), 판매상태, 며칠 전, 이모지, 사진 라벨, 설명)
PRODUCTS = [
    # 민지네
    ("minji", "digital", "아이패드 에어 5세대 64GB 스페이스 그레이", 520000, True, "LIKE_NEW", "SELLING", 1, "📱", "iPad Air",
     "작년 가을에 구매해서 필기용으로만 썼어요.\n배터리 성능 92%이고 기스 없이 깨끗해요.\n정품 충전기와 케이스 같이 드려요.\n서교동·합정역 근처 직거래 원해요."),
    ("minji", "appliance", "다이슨 V10 무선청소기 (배터리 교체함)", 230000, True, "GOOD", "SELLING", 3, "🧹", "Dyson V10",
     "3개월 전에 정품 배터리로 교체해서 흡입력 좋아요.\n헤드 3종, 거치대 포함이에요.\n부피가 커서 직거래만 가능해요."),
    ("minji", "furniture", "이케아 포엥 암체어 베이지", 45000, False, "GOOD", "RESERVED", 5, "🛋️", "POÄNG",
     "이사 가면서 정리해요. 쿠션 커버는 세탁해 두었어요.\n분해 없이 그대로 가져가셔야 해요 (승용차 뒷좌석 가능)."),
    ("minji", "women", "자라 울 블렌드 롱코트 S", 38000, False, "GOOD", "SELLING", 6, "🧥", "ZARA Coat",
     "두 번 입고 드라이클리닝 해두었어요.\n색상은 카멜이고 키 160 기준 무릎 아래 길이예요."),
    ("minji", "beauty", "이솝 레저렉션 핸드크림 75ml 미개봉 2개", 35000, False, "NEW", "SELLING", 2, "🧴", "Hand Cream",
     "선물 받았는데 같은 게 집에 있어서 올려요.\n2개 일괄이고 박스 미개봉이에요."),
    ("minji", "plant", "몬스테라 화분 (중형, 분갈이 완료)", 15000, False, "GOOD", "SELLING", 8, "🪴", "Monstera",
     "지난달에 분갈이해서 새 잎이 계속 나고 있어요.\n화분 포함 높이 70cm 정도예요."),
    ("minji", "kitchen", "발뮤다 더 토스터 화이트", 120000, True, "LIKE_NEW", "SELLING", 9, "🍞", "Toaster",
     "선물 받고 몇 번 안 썼어요. 박스와 설명서 있어요."),
    # 준호아빠
    ("junho", "kids", "스토케 트립트랩 하이체어 내추럴", 180000, True, "GOOD", "SELLING", 2, "🪑", "Tripp Trapp",
     "아이가 커서 정리해요. 베이비세트 포함이에요.\n생활 기스 조금 있지만 흔들림 없이 튼튼해요."),
    ("junho", "kids", "레고 듀플로 대형 버킷 세트", 25000, False, "FAIR", "SELLING", 4, "🧸", "DUPLO",
     "블록 개수는 정확히 세보지 않았지만 거의 다 있어요.\n깨끗하게 세척해 두었어요."),
    ("junho", "sports", "브롬톤 M6L 접이식 자전거 블랙", 1450000, True, "GOOD", "SELLING", 1, "🚲", "Brompton",
     "2023년 구매, 출퇴근용으로 1년 정도 탔어요.\n정기 점검 받았고 타이어 교체했어요.\n합정역 근처에서 시승 가능해요."),
    ("junho", "men", "나이키 에어포스 1 화이트 270", 55000, False, "GOOD", "SELLING", 7, "👟", "AF1 270",
     "사이즈 미스로 세 번 신었어요. 박스 있어요."),
    ("junho", "hobby", "닌텐도 스위치 OLED + 젤다 왕국의 눈물", 330000, True, "LIKE_NEW", "RESERVED", 3, "🎮", "Switch OLED",
     "필름 붙여서 써서 화면 깨끗해요. 조이콘 쏠림 없어요.\n젤다 칩 포함 가격이에요."),
    ("junho", "etc", "유아 카시트 무료 나눔해요", 0, False, "FAIR", "SELLING", 0, "📦", "Car Seat",
     "사용감은 있지만 쓰기에 문제없어요.\n필요하신 분께 나눔해요. 합정동으로 가지러 오셔야 해요."),
    # 서연이네책방
    ("seoyeon", "books", "파이썬 프로그래밍 책 3권 일괄", 18000, False, "GOOD", "SELLING", 1, "📚", "Python Books",
     "전공 수업 때 본 책이에요. 필기는 연필로 조금 있어요.\n3권 일괄로만 판매해요."),
    ("seoyeon", "books", "해리포터 영문판 전집 7권", 60000, True, "GOOD", "SELLING", 5, "📖", "Harry Potter",
     "페이퍼백 7권 세트예요. 책등 변색 조금 있어요."),
    ("seoyeon", "hobby", "필름카메라 올림푸스 뮤2", 280000, True, "GOOD", "SELLING", 4, "📷", "Olympus mju",
     "작동 잘 되고 플래시도 정상이에요.\n테스트 필름 현상 사진 보여드릴 수 있어요."),
    ("seoyeon", "ticket", "스타벅스 아메리카노 T 기프티콘 5장", 20000, False, "NEW", "SELLING", 0, "🎫", "Coffee x5",
     "유효기간 내년 2월까지예요. 채팅으로 바로 보내드려요."),
    ("seoyeon", "pet", "고양이 캣타워 대형 (직거래만)", 30000, False, "FAIR", "SELLING", 6, "🐱", "Cat Tower",
     "높이 150cm예요. 스크래처 부분은 사용감 있어요.\n분해해서 드릴 수 있어요."),
    ("seoyeon", "digital", "갤럭시 버즈2 프로 그라파이트", 90000, True, "LIKE_NEW", "SELLING", 10, "🎧", "Buds2 Pro",
     "케이스 기스 없이 깨끗해요. 이어팁 새것 포함이에요."),
    # 도현
    ("dohyun", "digital", "맥북 에어 M2 13인치 8GB/256GB 미드나이트", 950000, True, "LIKE_NEW", "SELLING", 2, "💻", "MacBook Air",
     "배터리 사이클 48회, 애플케어 내년 3월까지 남아 있어요.\n박스 풀구성이고 정자역에서 직거래 가능해요."),
    ("dohyun", "appliance", "LG 퓨리케어 공기청정기 (필터 새것)", 150000, True, "GOOD", "SELLING", 5, "🌬️", "Air Purifier",
     "필터 지난주에 새로 갈았어요. 소음 없이 잘 돼요."),
    ("dohyun", "furniture", "원목 4인 식탁 세트", 120000, True, "FAIR", "SELLING", 8, "🪵", "Dining Table",
     "의자 4개 포함이에요. 상판에 생활 기스 있어요.\n엘리베이터 있는 아파트 1층에서 가져가셔야 해요."),
    ("dohyun", "sports", "요가매트 + 폼롤러 세트", 12000, False, "GOOD", "SELLING", 3, "🧘", "Yoga Set",
     "매트 두께 10mm예요. 깨끗하게 닦아 두었어요."),
    # 의심 판매글 (규칙 기반 사기 탐지가 걸리도록 작성)
    ("quick", "digital", "아이폰 15 프로 256GB 미개봉 급처", 250000, False, "NEW", "SELLING", 0, "📱", "iPhone 15 Pro",
     "해외 출장 중이라 택배거래만 가능해요.\n선입금 해주시면 바로 보내드려요.\n카톡 아이디 quicksale77 로 연락 주세요.\n국민은행 123456-78-901234 입금 확인 후 발송해요."),
]

# 카테고리별 사진 배경색 (브랜드 틸/스톤 톤과 어울리는 파스텔)
PALETTES = {
    "digital": ((226, 232, 240), (148, 163, 184)),
    "appliance": ((231, 229, 228), (168, 162, 158)),
    "furniture": ((245, 235, 220), (194, 164, 120)),
    "kitchen": ((254, 243, 199), (217, 170, 90)),
    "kids": ((254, 226, 226), (240, 150, 150)),
    "women": ((250, 232, 255), (200, 150, 210)),
    "men": ((224, 231, 255), (130, 150, 220)),
    "beauty": ((252, 231, 243), (230, 150, 190)),
    "sports": ((220, 252, 231), (110, 190, 140)),
    "hobby": ((237, 233, 254), (160, 140, 230)),
    "books": ((254, 249, 195), (200, 180, 90)),
    "ticket": ((255, 237, 213), (240, 160, 100)),
    "pet": ((236, 252, 203), (150, 200, 90)),
    "plant": ((204, 251, 241), (60, 170, 150)),
    "etc": ((245, 245, 244), (168, 162, 158)),
}

KOREAN_FONT_CANDIDATES = [
    "~/.local/share/fonts/Pretendard-Bold.otf",
    "/usr/share/fonts/opentype/pretendard/Pretendard-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]
EMOJI_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
]


def _first_existing(paths):
    for raw in paths:
        path = Path(os.path.expanduser(raw))
        if path.exists():
            return str(path)
    return None


class ImageMaker:
    """상품 사진 대용 이미지 (배경 + 다각형 장식 + 큰 이모지 + 라벨)."""

    SIZE = 800

    def __init__(self, seed=7):
        from PIL import ImageFont

        self.rng = random.Random(seed)
        self.ImageFont = ImageFont
        font_path = _first_existing(KOREAN_FONT_CANDIDATES)
        self.label_font = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default()
        self.emoji_font = None
        emoji_path = _first_existing(EMOJI_FONT_CANDIDATES)
        if emoji_path:
            try:
                # Noto Color Emoji 는 109px 비트맵만 지원
                self.emoji_font = ImageFont.truetype(emoji_path, 109)
            except OSError:
                self.emoji_font = None

    def _emoji(self, char, size):
        from PIL import Image, ImageDraw

        if not self.emoji_font:
            return None
        canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        try:
            ImageDraw.Draw(canvas).text((80, 80), char, font=self.emoji_font, embedded_color=True, anchor="mm")
        except (OSError, ValueError, TypeError):
            return None
        bbox = canvas.getbbox()
        if not bbox:
            return None
        canvas = canvas.crop(bbox)
        scale = size / max(canvas.size)
        return canvas.resize((max(1, int(canvas.width * scale)), max(1, int(canvas.height * scale))), Image.LANCZOS)

    def make(self, slug, emoji, label, variant=0) -> bytes:
        from PIL import Image, ImageDraw

        bg, accent = PALETTES.get(slug, PALETTES["etc"])
        if variant:  # 두 번째 사진은 살짝 어둡게 + 다른 구도
            bg = tuple(max(0, c - 14) for c in bg)
        size = self.SIZE
        img = Image.new("RGB", (size, size), bg)
        draw = ImageDraw.Draw(img, "RGBA")

        # 다각형(폴리) 장식
        for _ in range(4):
            cx, cy = self.rng.randint(0, size), self.rng.randint(0, size)
            r = self.rng.randint(90, 260)
            sides = self.rng.choice([3, 5, 6])
            points = []
            start = self.rng.random() * math.pi
            for i in range(sides):
                angle = start + 2 * math.pi * i / sides
                points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            draw.polygon(points, fill=accent + (46,))

        # 바닥 그림자 + 받침
        center_y = 360 if variant == 0 else 400
        draw.ellipse((210, center_y + 170, 590, center_y + 215), fill=(0, 0, 0, 28))

        icon = self._emoji(emoji, 340 if variant == 0 else 280)
        if icon is not None:
            if variant:
                icon = icon.rotate(-12, expand=True, resample=Image.BICUBIC)
            img.paste(icon, ((size - icon.width) // 2, center_y - icon.height // 2), icon)
        else:
            # 이모지 폰트가 없으면 둥근 사각형으로 대신
            draw.rounded_rectangle((250, center_y - 150, 550, center_y + 150), radius=36, fill=accent + (200,))

        # 라벨 (흰 칩)
        text_w = draw.textlength(label, font=self.label_font)
        chip_w = int(text_w) + 64
        x0 = (size - chip_w) // 2
        y0 = 640
        draw.rounded_rectangle((x0, y0, x0 + chip_w, y0 + 84), radius=42, fill=(255, 255, 255, 225))
        draw.text((size // 2, y0 + 42), label, font=self.label_font, fill=(41, 37, 36), anchor="mm")

        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=84, optimize=True)
        return buffer.getvalue()


class Command(BaseCommand):
    help = "개발용 데모 데이터(사용자/상품/채팅/후기/알림)를 만들어요. 운영 환경에서는 실행되지 않아요."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="기존 데모 데이터를 지우고 다시 만들어요.")
        parser.add_argument("--with-ai", action="store_true", help="사기 탐지에 실제 Gemini 판단을 사용해요.")

    def handle(self, *args, **options):
        self._guard()
        demo_users = User.objects.filter(username__startswith=USERNAME_PREFIX)
        if demo_users.exists():
            if not options["reset"]:
                self.stdout.write(self.style.WARNING("데모 데이터가 이미 있어요. 다시 만들려면 --reset 을 붙여 주세요."))
                return
            count = demo_users.count()
            self._remove_media(list(demo_users.values_list("pk", flat=True)))
            demo_users.delete()  # 상품/채팅/후기/알림/신고는 CASCADE
            self.stdout.write(f"기존 데모 사용자 {count}명과 관련 데이터를 지웠어요.")

        if options["with_ai"]:
            self._seed()
        else:
            # 기본은 규칙 기반 사기 탐지만 (빠르고 오프라인에서도 동작)
            with override_settings(GEMINI_API_KEY=""):
                self._seed()

    def _remove_media(self, user_ids):
        # 로컬 MEDIA_ROOT 의 데모 상품 사진 폴더 정리 (products/<판매자 id>/...)
        import shutil

        root = Path(settings.MEDIA_ROOT) / "products"
        for user_id in user_ids:
            folder = root / str(user_id)
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)

    # ───────── 안전장치 ─────────
    def _guard(self):
        engine = settings.DATABASES["default"]["ENGINE"]
        if os.getenv("RENDER") or not settings.DEBUG:
            raise CommandError("seed_demo 는 개발 환경(DEBUG=True)에서만 실행할 수 있어요.")
        if "sqlite" not in engine and os.getenv("SEED_DEMO_ALLOW_POSTGRES") != "1":
            raise CommandError("SQLite 개발 DB에서만 실행해요. (다른 DB면 SEED_DEMO_ALLOW_POSTGRES=1)")
        if getattr(settings, "USE_SUPABASE_STORAGE", False):
            raise CommandError("로컬 저장소(MEDIA_ROOT)에서만 실행해요. USE_SUPABASE_STORAGE 를 꺼 주세요.")

    # ───────── 생성 ─────────
    @transaction.atomic
    def _seed(self):
        now = timezone.now()
        self.maker = ImageMaker()
        users = self._create_users()
        products = self._create_products(users, now)
        self._wishlists_and_views(users, products)
        rooms = self._chats(users, products, now)
        self._trades(users, products, rooms)
        self._misc(users, products)

        sold = sum(1 for p in products if p.status == Product.Status.SOLD)
        self.stdout.write(
            self.style.SUCCESS(
                f"데모 데이터를 만들었어요: 사용자 {len(users)}명, 상품 {len(products)}개(거래완료 {sold}), "
                f"채팅방 {ChatRoom.objects.filter(seller__in=users.values()).count()}개, "
                f"메시지 {ChatMessage.objects.filter(room__seller__in=users.values()).count()}개, "
                f"알림 {Notification.objects.filter(user__in=users.values()).count()}개"
            )
        )
        self.stdout.write(f"로그인: demo_minji / {PASSWORD} (다른 계정: demo_junho, demo_seoyeon, demo_dohyun, demo_quick)")

    def _create_users(self):
        from datetime import date

        users = {}
        for key, nickname, name, birth, phone, region_key, bio, temp in USERS:
            region = Region.objects.filter(sido=region_key[0], sigungu=region_key[1], dong=region_key[2]).first()
            # 다른 사람이 같은 닉네임/번호를 이미 쓰고 있으면 비워서 충돌을 피한다
            if Profile.objects.filter(nickname=nickname).exists():
                nickname = f"{nickname}_{key}"[:20]
            if Profile.objects.filter(phone=phone).exists():
                phone = None
            user = register_user(
                username=USERNAME_PREFIX + key,
                password=PASSWORD,
                nickname=nickname,
                name=name,
                birth_date=date.fromisoformat(birth) if birth else None,
                phone=phone,
                region=region,
            )
            Profile.objects.filter(user=user).update(bio=bio, manner_temperature=Decimal(temp))
            user.refresh_from_db()
            users[key] = user
        return users

    def _create_products(self, users, now):
        categories = {c.slug: c for c in Category.objects.all()}
        products = []
        for index, row in enumerate(PRODUCTS):
            seller_key, slug, title, price, negotiable, condition, status, days_ago, emoji, label, content = row
            seller = users[seller_key]
            images = [
                SimpleUploadedFile(
                    f"demo_{index}_{n}.jpg", self.maker.make(slug, emoji, label, variant=n), content_type="image/jpeg"
                )
                for n in range(2 if index % 3 else 1)  # 일부는 사진 1장
            ]
            product = create_product(
                seller,
                {
                    "title": title,
                    "category": categories[slug],
                    "condition": condition,
                    "price": price,
                    "negotiable": negotiable,
                    "region": seller.profile.region,
                    "content": content,
                },
                images=images,
            )
            created = now - timedelta(days=days_ago, hours=random.Random(index).randint(1, 20))
            Product.objects.filter(pk=product.pk).update(
                created_at=created,
                updated_at=created,
                status=status,
                view_count=random.Random(index * 7).randint(8, 160),
            )
            product.refresh_from_db()
            products.append(product)
        return products

    def _wishlists_and_views(self, users, products):
        p = products
        wishes = {
            "minji": [9, 15, 19],
            "junho": [19, 14],
            "seoyeon": [0, 1, 19],
            "dohyun": [0, 7, 11],
            "quick": [],
        }
        for key, indexes in wishes.items():
            for i in indexes:
                toggle_wishlist(users[key], p[i])
        views = {
            "minji": [9, 19, 15, 14, 23],
            "junho": [19, 0, 13],
            "seoyeon": [0, 1, 23, 9],
            "dohyun": [0, 7, 11, 13],
        }
        for key, indexes in views.items():
            for i in indexes:
                record_view(p[i], users[key], count=False)

        # 가격 인하 → 찜한 사람(서연, 도현)에게 가격 변동 알림
        update_product(p[0], {"price": 490000})
        p[0].refresh_from_db()

    def _chat(self, product, buyer, script, start, read_upto=None):
        """script: [(보낸 사람, 내용)] — 메시지를 보내고 시각을 start 부터 몇 분 간격으로 맞춘다.

        read_upto: 앞에서부터 몇 개를 읽음 처리할지 (None 이면 전부).
        """
        room, _ = get_or_create_room(product, buyer)
        messages = [send_message(room, sender, content) for sender, content in script]
        when = start
        for message in messages:
            when += timedelta(minutes=random.Random(message.pk).randint(1, 9))
            ChatMessage.objects.filter(pk=message.pk).update(created_at=when)
        ChatRoom.objects.filter(pk=room.pk).update(last_message_at=when, created_at=start, updated_at=when)
        upto = len(messages) if read_upto is None else read_upto
        read_ids = [m.pk for m in messages[:upto]]
        ChatMessage.objects.filter(pk__in=read_ids).update(is_read=True, read_at=when)
        room.refresh_from_db()
        return room

    def _chats(self, users, products, now):
        u, p = users, products
        rooms = {}
        rooms["brompton"] = self._chat(p[9], u["dohyun"], [
            (u["dohyun"], "안녕하세요! 브롬톤 아직 판매 중인가요?"),
            (u["junho"], "네 판매 중이에요. 주말에 합정역 근처에서 거래 가능해요."),
            (u["dohyun"], "혹시 130만원에 가능할까요? 바로 가지러 갈게요."),
        ], now - timedelta(minutes=50), read_upto=2)
        rooms["ipad"] = self._chat(p[0], u["junho"], [
            (u["junho"], "아이패드 배터리 성능 몇 %인가요?"),
            (u["minji"], "92%예요. 충전기랑 케이스도 같이 드려요."),
            (u["junho"], "좋네요! 45만원에 네고 될까요?"),
            (u["minji"], "가격을 이미 내려서 47만원까지 가능해요 :)"),
            (u["junho"], "그럼 47만원에 할게요. 내일 저녁 7시 서교동 괜찮으세요?"),
        ], now - timedelta(hours=3), read_upto=4)
        rooms["switch"] = self._chat(p[11], u["minji"], [
            (u["minji"], "스위치 예약 가능할까요? 토요일에 가지러 갈게요."),
            (u["junho"], "네 토요일까지 예약해 둘게요!"),
            (u["minji"], "감사합니다. 토요일 오후 2시에 합정역 7번 출구에서 봬요."),
        ], now - timedelta(days=1, hours=2))
        rooms["toaster"] = self._chat(p[6], u["seoyeon"], [
            (u["seoyeon"], "토스터 아직 있나요?"),
            (u["minji"], "네 있어요. 오늘 저녁에 거래 가능해요."),
            (u["seoyeon"], "좋아요. 망원역에서 8시에 뵐게요."),
            (u["minji"], "네 도착하면 연락드릴게요!"),
        ], now - timedelta(days=6))
        rooms["buds"] = self._chat(p[18], u["minji"], [
            (u["minji"], "버즈 사고 싶어요. 노이즈캔슬링 잘 되나요?"),
            (u["seoyeon"], "네 잘 돼요. 펌웨어 최신으로 업데이트해 두었어요."),
            (u["minji"], "내일 점심에 망원시장 앞에서 거래할게요."),
        ], now - timedelta(days=8))
        rooms["scam"] = self._chat(p[23], u["seoyeon"], [
            (u["seoyeon"], "아이폰 실물 사진 더 볼 수 있을까요?"),
            (u["quick"], "카톡 아이디 quicksale77 로 연락주세요. 선입금하시면 바로 택배 보내드려요."),
        ], now - timedelta(minutes=20), read_upto=1)
        rooms["books"] = self._chat(p[13], u["dohyun"], [
            (u["dohyun"], "책 상태 깨끗한가요? 판교까지 택배도 가능할까요?"),
        ], now - timedelta(minutes=8), read_upto=0)
        rooms["macbook"] = self._chat(p[19], u["minji"], [
            (u["minji"], "맥북 배터리 상태 괜찮나요? 조금만 싸게 해주실 수 있을까요?"),
            (u["dohyun"], "배터리 효율 97%예요. 92만원까지는 가능해요."),
        ], now - timedelta(hours=20))
        return rooms

    def _trades(self, users, products, rooms):
        u, p = users, products
        # 토스터: 민지 → 서연 판매, 양쪽 후기
        complete_trade(p[6], u["minji"], u["seoyeon"])
        create_review(p[6], u["seoyeon"], 5, ["친절해요", "시간 약속을 잘 지켜요", "상품 상태가 설명과 같아요"],
                      "설명대로 거의 새것이었어요. 친절하게 거래해 주셔서 감사해요!")
        create_review(p[6], u["minji"], 5, ["시간 약속을 잘 지켜요", "거래를 깔끔하게 마무리했어요"],
                      "약속 시간에 맞춰 오셨어요. 좋은 거래였어요.")
        # 버즈: 서연 → 민지 판매, 구매자 후기만 (판매자 후기는 아직)
        complete_trade(p[18], u["seoyeon"], u["minji"])
        create_review(p[18], u["minji"], 4, ["응답이 빨라요", "가격이 합리적이에요"], "응답이 빨라서 좋았어요.")
        # 후기/거래 알림 시각을 실제 거래 시점(며칠 전)으로 맞춘다
        for product, days in ((p[6], 5), (p[18], 7)):
            when = timezone.now() - timedelta(days=days)
            Review.objects.filter(product=product).update(created_at=when, updated_at=when)
            Product.objects.filter(pk=product.pk).update(updated_at=when)
            title = product.title
            Notification.objects.filter(
                kind__in=[Notification.Kind.REVIEW, Notification.Kind.STATUS_CHANGE], message__contains=title
            ).update(created_at=when, is_read=True)
            product.refresh_from_db()

    def _misc(self, users, products):
        u, p = users, products
        # 의심 상품 신고 (접수 상태)
        create_report(u["seoyeon"], reason=Report.Reason.FRAUD, product=p[23],
                      detail="선입금과 카톡 연락을 요구해요.")
        # 환영 알림
        for key in ("minji", "junho", "seoyeon", "dohyun"):
            notify(
                u[key],
                Notification.Kind.SYSTEM,
                "폴리마켓에 오신 걸 환영해요! 내 동네 새 상품을 둘러보세요.",
                url=reverse("products:list"),
            )
        # 오래된 알림 일부는 읽음 처리
        Notification.objects.filter(user__in=u.values(), kind=Notification.Kind.SYSTEM).update(is_read=True)
        # 최근 본 상품 순서가 자연스럽도록 시각 분산
        for index, view in enumerate(RecentView.objects.filter(user__in=u.values()).order_by("pk")):
            RecentView.objects.filter(pk=view.pk).update(viewed_at=timezone.now() - timedelta(hours=index))
