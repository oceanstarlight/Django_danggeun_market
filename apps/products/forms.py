"""상품 폼 (등록/수정, 목록 필터)."""

from django import forms
from django.conf import settings

from apps.accounts.models import Region
from apps.core.forms import StyledFormMixin
from apps.core.storage import StorageError, validate_image

from .models import Category, Product, ProductImage

MAX_IMAGES = 10
MAX_PRICE = 1_000_000_000  # 10억 원


class MultipleFileInput(forms.FileInput):
    """여러 파일을 한 번에 고르는 file input."""

    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    """여러 이미지를 리스트로 받는 필드 (빈 값이면 [])."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        files = [f for f in files if f]
        cleaned = [super(MultipleImageField, self).clean(f, initial) for f in files]
        for f in cleaned:
            try:
                validate_image(f)
            except StorageError as exc:
                raise forms.ValidationError(f"{f.name}: {exc}") from exc
            _verify_image_content(f)
        return cleaned


def _verify_image_content(file):
    """Pillow 로 실제 이미지인지 확인 (확장자만 바꾼 파일 차단). HEIC 는 Pillow 미지원이라 건너뜀."""
    name = (file.name or "").lower()
    if name.endswith((".heic", ".heif")):
        return
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow 는 requirements 에 포함
        return
    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow 예외 타입이 다양함
        raise forms.ValidationError(f"{file.name}: 이미지 파일을 읽을 수 없어요.") from exc
    finally:
        file.seek(0)


class ProductForm(StyledFormMixin, forms.ModelForm):
    """상품 등록/수정 폼. 이미지(name=images)와 기존 이미지 삭제(remove_images)를 함께 받는다."""

    images = MultipleImageField(
        label="사진",
        help_text=f"최대 {MAX_IMAGES}장까지 올릴 수 있어요. 첫 번째 사진이 대표 사진이 돼요.",
    )
    remove_images = forms.ModelMultipleChoiceField(
        label="삭제할 사진",
        queryset=ProductImage.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Product
        fields = ["title", "category", "condition", "price", "negotiable", "region", "content"]
        labels = {
            "title": "제목",
            "category": "카테고리",
            "condition": "상품 상태",
            "price": "가격",
            "negotiable": "가격 제안 받기",
            "region": "거래 동네",
            "content": "자세한 설명",
        }
        help_texts = {
            "price": "0원을 입력하면 나눔으로 올라가요.",
            "region": "",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "어떤 물건인지 알 수 있게 적어 주세요", "maxlength": 100}),
            "price": forms.NumberInput(
                attrs={"placeholder": "가격을 입력해 주세요", "inputmode": "numeric", "min": 0, "step": 1}
            ),
            "content": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": "브랜드, 모델명, 구매 시기, 사용감, 하자 여부 등을 적어 주면 거래가 빨라져요.\n\n"
                    "안전한 거래를 위해 선입금 요구나 외부 메신저 연락은 피해 주세요.",
                    "data-autoresize": "",
                    "data-autoresize-max": "640",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["category"].queryset = Category.objects.all()
        self.fields["category"].empty_label = "카테고리를 골라 주세요"
        self.fields["region"].queryset = Region.objects.all()
        self.fields["region"].empty_label = "동네를 골라 주세요"
        self.fields["region"].required = True
        self.fields["price"].max_value = MAX_PRICE
        # 파일 input 은 커스텀 업로드 타일로 대체 (스크린리더/키보드용으로만 남김)
        self.fields["images"].widget.attrs.update(
            {"class": "peer sr-only", "accept": "image/*", "data-preview-target": "#image-preview"}
        )
        if self.instance.pk:
            self.fields["remove_images"].queryset = self.instance.images.all()
        else:
            # 새 글: 기본 거래 동네 = 내 동네
            region = _user_region(user)
            if region and not self.initial.get("region"):
                self.initial["region"] = region.pk
        self.fields["images"].widget.attrs["data-preview-max"] = str(self.remaining_slots)

    @property
    def existing_images(self):
        if not self.instance.pk:
            return []
        return list(self.instance.images.all())

    @property
    def remaining_slots(self):
        return max(0, MAX_IMAGES - len(self.existing_images))

    @property
    def removed_image_ids(self):
        """다시 그릴 때 '삭제 예정' 체크 상태를 유지하기 위한 id 집합."""
        if self.is_bound:
            return {str(v) for v in self.data.getlist(self.add_prefix("remove_images"))}
        return set()

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if len(title) < 2:
            raise forms.ValidationError("제목을 2자 이상 적어 주세요.")
        return title

    def clean_content(self):
        content = (self.cleaned_data.get("content") or "").strip()
        if len(content) < 5:
            raise forms.ValidationError("설명을 5자 이상 적어 주세요.")
        return content

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is not None and price > MAX_PRICE:
            raise forms.ValidationError("가격이 너무 커요.")
        return price

    def clean(self):
        cleaned = super().clean()
        new_images = cleaned.get("images") or []
        removed = cleaned.get("remove_images") or []
        total = len(self.existing_images) - len(removed) + len(new_images)
        if total > MAX_IMAGES:
            self.add_error("images", f"사진은 최대 {MAX_IMAGES}장까지 올릴 수 있어요. (지금 {total}장)")
        # 나눔이면 가격 제안은 의미가 없어요
        if cleaned.get("price") == 0:
            cleaned["negotiable"] = False
        return cleaned

    def product_data(self):
        """서비스 레이어에 넘길 모델 필드 dict."""
        return {name: self.cleaned_data[name] for name in self._meta.fields if name in self.cleaned_data}


def _user_region(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.profile.region
    except Exception:  # noqa: BLE001 - 프로필 없는 사용자
        return None


class ProductFilterForm(forms.Form):
    """목록 GET 파라미터 파싱/검증 (잘못된 값은 기본값으로)."""

    SORT_CHOICES = [
        ("latest", "최신순"),
        ("popular", "인기순"),
        ("price_asc", "낮은 가격순"),
        ("price_desc", "높은 가격순"),
    ]
    STATUS_CHOICES = [("all", "전체"), ("selling", "거래 가능만")]

    q = forms.CharField(required=False, max_length=50)
    category = forms.CharField(required=False, max_length=30)
    region = forms.CharField(required=False, max_length=10)
    status = forms.ChoiceField(required=False, choices=STATUS_CHOICES)
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def params(self):
        """검증된 값 dict. 잘못된 값은 버린다."""
        data = {"q": "", "category": "", "region": "", "status": "all", "sort": "latest"}
        if not self.is_valid():
            # 필드별로 유효한 값만 살린다
            for name in data:
                if name not in self.errors and name in getattr(self, "cleaned_data", {}):
                    data[name] = self.cleaned_data[name] or data[name]
            return data
        for name in data:
            value = self.cleaned_data.get(name)
            if value:
                data[name] = value.strip() if isinstance(value, str) else value
        return data


def max_upload_mb():
    return getattr(settings, "MAX_UPLOAD_IMAGE_SIZE", 10 * 1024 * 1024) // (1024 * 1024)
