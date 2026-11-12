"""AI 입력 이미지 전처리.

업로드 파일을 PIL 로 검증한 뒤 긴 변 1024px JPEG 로 줄인다.
→ 토큰/업로드 비용 절감 + 같은 사진이면 같은 바이트가 나와 캐시 키가 안정적이다.
"""

from __future__ import annotations

import io

from django.conf import settings

from .client import AIServiceError

MAX_SIDE = 1024
JPEG_QUALITY = 85
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO", "BMP"}


class AIInputError(AIServiceError):
    """사용자 입력 문제 (400). user_message 를 그대로 보여준다."""


def normalize_image(raw: bytes) -> tuple[bytes, str]:
    """이미지 바이트 → (JPEG 바이트, "image/jpeg"). 이미지가 아니면 AIInputError."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise AIInputError("JPG, PNG, WEBP 사진만 분석할 수 있어요.")
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)  # 휴대폰 사진 회전 보정
            if img.mode not in ("RGB", "L"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
    except AIInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AIInputError("사진 파일을 읽지 못했어요. 다른 사진으로 시도해 주세요.", detail=str(exc)) from exc


def prepare_uploaded_images(files, *, max_count: int = 2, required: bool = True) -> list[tuple[bytes, str]]:
    """request.FILES 목록 → [(bytes, mime)] (앞에서부터 max_count 장)."""
    files = [f for f in files if f]
    if not files:
        if required:
            raise AIInputError("사진을 1장 이상 올려 주세요.")
        return []
    limit = getattr(settings, "MAX_UPLOAD_IMAGE_SIZE", 10 * 1024 * 1024)
    prepared = []
    for upload in files[:max_count]:
        if upload.size > limit:
            raise AIInputError(f"사진은 한 장에 {limit // (1024 * 1024)}MB까지 올릴 수 있어요.")
        prepared.append(normalize_image(upload.read()))
    return prepared
