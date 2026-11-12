"""이미지 업로드 서비스.

- 개발/테스트: MEDIA_ROOT/<folder>/<uuid>.<ext> 에 저장하고 MEDIA_URL 경로를 반환
- 운영(USE_SUPABASE_STORAGE): Supabase Storage 에 업로드하고 public URL 반환
Supabase 클라이언트는 실제로 필요할 때만 만든다(지연 생성).
"""

import logging
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif"}
DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10MB

# 저장 확장자 -> Content-Type. 클라이언트가 보낸 content_type 은 절대 쓰지 않는다.
CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
}
# Pillow 가 알려 주는 실제 포맷 -> 저장 확장자 (MPO 는 아이폰 JPEG)
PIL_FORMATS = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


class StorageError(Exception):
    """업로드 실패/검증 실패. str(e) 는 사용자에게 보여줄 수 있는 문구."""


_supabase_client = None


def _get_supabase_client():
    """Supabase 클라이언트를 처음 호출될 때 한 번만 만든다."""
    global _supabase_client
    if _supabase_client is None:
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY
        if not url or not key:
            raise StorageError("이미지 저장소 설정이 없어요. 관리자에게 문의해 주세요.")
        from supabase import create_client  # 무거운 import 도 지연

        _supabase_client = create_client(url, key)
    return _supabase_client


def _max_size():
    return getattr(settings, "MAX_UPLOAD_IMAGE_SIZE", DEFAULT_MAX_SIZE)


def _check_name_and_size(file):
    """이름(확장자)과 크기만 빠르게 검사한다."""
    if not file or not getattr(file, "name", ""):
        raise StorageError("이미지 파일을 선택해 주세요.")
    ext = PurePosixPath(file.name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise StorageError("jpg, png, gif, webp 이미지만 올릴 수 있어요.")
    size = getattr(file, "size", None)
    if size is not None and size > _max_size():
        raise StorageError("이미지는 10MB 이하만 올릴 수 있어요.")
    if size == 0:
        raise StorageError("비어 있는 파일이에요.")


def detect_image_format(data: bytes) -> str:
    """파일 내용을 보고 실제 이미지 포맷의 확장자를 돌려준다. 이미지가 아니면 StorageError.

    확장자만 바꾼 HTML/JS 같은 파일을 막기 위해 서버에서 직접 판별한다.
    """
    # HEIC/HEIF 는 Pillow 기본 미지원 → ISO BMFF 'ftyp' 박스의 브랜드로 판별
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS:
        return "heic" if data[8:12] != b"mif1" else "heif"
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow 예외 타입이 다양함
        raise StorageError("이미지 파일을 읽을 수 없어요.") from exc
    ext = PIL_FORMATS.get(fmt or "")
    if not ext:
        raise StorageError("jpg, png, gif, webp 이미지만 올릴 수 있어요.")
    return ext


def validate_image(file):
    """확장자·크기·실제 내용을 검사하고, 내용 기준 저장 확장자를 반환한다."""
    _check_name_and_size(file)
    return detect_image_format(_read_bytes(file))


def _clean_folder(folder):
    # 경로 조작 방지: 상대경로/상위경로 제거
    parts = [p for p in str(folder or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(parts) or "uploads"


def _read_bytes(file):
    if hasattr(file, "seek"):
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001 - 일부 스트림은 seek 불가
            pass
    data = file.read()
    if hasattr(file, "seek"):
        try:
            file.seek(0)  # 이후 다른 곳(AI 등)에서 다시 읽을 수 있게
        except Exception:  # noqa: BLE001
            pass
    return data


def upload_image(file, folder: str) -> str:
    """이미지를 저장하고 접근 가능한 URL(또는 MEDIA_URL 경로)을 반환한다.

    실패하면 StorageError 를 던진다.
    """
    _check_name_and_size(file)
    data = _read_bytes(file)
    if len(data) > _max_size():
        raise StorageError("이미지는 10MB 이하만 올릴 수 있어요.")
    # 확장자·Content-Type 모두 실제 내용에서 정한다 (클라이언트 값 무시)
    ext = detect_image_format(data)
    folder = _clean_folder(folder)
    path = f"{folder}/{uuid.uuid4().hex}.{ext}"

    if settings.USE_SUPABASE_STORAGE:
        return _upload_supabase(path, data, ext)
    return _upload_local(path, data)


def _upload_local(path, data):
    try:
        storage = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)
        saved = storage.save(path, ContentFile(data))
        return storage.url(saved)
    except OSError as exc:
        logger.exception("로컬 이미지 저장 실패")
        raise StorageError("이미지를 저장하지 못했어요. 잠시 후 다시 시도해 주세요.") from exc


def _upload_supabase(path, data, ext):
    content_type = CONTENT_TYPES[ext]
    try:
        bucket = _get_supabase_client().storage.from_(settings.SUPABASE_BUCKET)
        bucket.upload(
            path=path,
            file=data,
            file_options={"content-type": content_type, "upsert": "false"},
        )
        # 일부 SDK 버전은 URL 끝에 "?" 를 붙여서 제거
        return bucket.get_public_url(path).rstrip("?")
    except StorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - SDK 예외 타입이 다양함
        logger.exception("Supabase 이미지 업로드 실패")
        raise StorageError("이미지를 업로드하지 못했어요. 잠시 후 다시 시도해 주세요.") from exc
