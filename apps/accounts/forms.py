"""회원가입 / 로그인 / 프로필 수정 폼."""

import re
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.urls import reverse_lazy
from django.utils.choices import BaseChoiceIterator

from apps.core.forms import StyledFormMixin
from apps.core.storage import StorageError, validate_image

from . import selectors
from .models import Profile, Region

User = get_user_model()

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{4,20}$")
NICKNAME_RE = re.compile(r"^[가-힣a-zA-Z0-9_]{2,20}$")
PHONE_RE = re.compile(r"^01[016789]\d{7,8}$")

BIO_MAX_LENGTH = 300


# ───────── 형식 검사 (폼 + 실시간 중복 확인에서 함께 사용) ─────────
def username_format_error(value: str) -> str | None:
    if not USERNAME_RE.match(value or ""):
        return "아이디는 영문, 숫자, 밑줄(_)로 4~20자 입력해 주세요."
    return None


def nickname_format_error(value: str) -> str | None:
    if not NICKNAME_RE.match(value or ""):
        return "닉네임은 한글, 영문, 숫자, 밑줄(_)로 2~20자 입력해 주세요."
    return None


def normalize_phone(value: str) -> str | None:
    """숫자만 남겨 '010-1234-5678' 형식으로 바꾼다. 형식이 틀리면 None."""
    digits = re.sub(r"\D", "", value or "")
    if not PHONE_RE.match(digits):
        return None
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"


# ───────── 동네 선택 (시/군/구별 optgroup) ─────────
class RegionChoiceField(forms.ModelChoiceField):
    """'서울특별시' 그룹 아래 '강남구 역삼동'을 고르는 select."""

    def __init__(self, **kwargs):
        kwargs.setdefault("queryset", Region.objects.all())
        kwargs.setdefault("empty_label", "동네를 선택해 주세요")
        kwargs.setdefault("label", "내 동네")
        kwargs.setdefault("error_messages", {"required": "동네를 선택해 주세요.", "invalid_choice": "목록에서 동네를 골라 주세요."})
        super().__init__(**kwargs)

    def grouped_choices(self):
        # 실제 렌더링 시점에만 조회 (쿼리 1번)
        groups: dict[str, list] = {}
        for region in self.queryset:
            groups.setdefault(region.sido, []).append((region.pk, f"{region.sigungu} {region.dong}"))
        if self.empty_label is not None:
            yield ("", self.empty_label)
        yield from groups.items()

    def _get_choices(self):
        # 지연 iterable 반환 — 클래스 정의/폼 생성 시 DB를 건드리지 않게 (migrate 전에도 import 가능)
        return _LazyGroupedChoices(self)

    choices = property(_get_choices, forms.ChoiceField.choices.fset)


class _LazyGroupedChoices(BaseChoiceIterator):
    """순회할 때마다 RegionChoiceField.grouped_choices()를 새로 계산한다."""

    def __init__(self, field):
        self.field = field

    def __iter__(self):
        return iter(list(self.field.grouped_choices()))


def _check_attrs(field_name: str, **extra):
    """입력하는 동안 HTMX로 중복 여부를 확인하는 속성."""
    attrs = {
        "hx-get": reverse_lazy("accounts:check_duplicate"),
        "hx-trigger": "input changed delay:500ms, blur changed",
        "hx-target": f"#check-{field_name}",
        "hx-swap": "innerHTML",
        "data-silent": "",
    }
    attrs.update(extra)
    return attrs


# ───────── 회원가입 ─────────
class SignUpForm(StyledFormMixin, UserCreationForm):
    nickname = forms.CharField(
        label="닉네임",
        max_length=20,
        help_text="이웃에게 보여지는 이름이에요.",
        widget=forms.TextInput(attrs=_check_attrs("nickname", autocomplete="nickname", placeholder="예: 폴리")),
    )
    name = forms.CharField(
        label="이름",
        max_length=30,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "실명을 입력해 주세요"}),
    )
    birth_date = forms.DateField(
        label="생년월일",
        widget=forms.DateInput(attrs={"type": "date", "autocomplete": "bday"}, format="%Y-%m-%d"),
        error_messages={"invalid": "날짜를 올바르게 입력해 주세요."},
    )
    phone = forms.CharField(
        label="휴대폰 번호",
        max_length=20,
        widget=forms.TextInput(
            attrs=_check_attrs(
                "phone", type="tel", inputmode="numeric", autocomplete="tel", placeholder="010-1234-5678"
            )
        ),
    )
    region = RegionChoiceField()

    field_order = ["username", "nickname", "name", "birth_date", "phone", "region", "password1", "password2"]

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)
        labels = {"username": "아이디"}
        help_texts = {"username": "영문, 숫자, 밑줄(_)로 4~20자예요."}
        widgets = {
            "username": forms.TextInput(
                attrs=_check_attrs("username", autocomplete="username", autocapitalize="none", placeholder="아이디")
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].max_length = 20
        self.fields["password1"].label = "비밀번호"
        self.fields["password1"].help_text = "8자 이상, 너무 흔하거나 숫자로만 된 비밀번호는 쓸 수 없어요."
        self.fields["password2"].label = "비밀번호 확인"
        self.fields["password2"].help_text = ""
        self.fields["password2"].widget.attrs["placeholder"] = "한 번 더 입력해 주세요"
        today = date.today().isoformat()
        self.fields["birth_date"].widget.attrs.update({"max": today, "min": "1900-01-01"})

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        error = username_format_error(username)
        if error:
            raise forms.ValidationError(error)
        if selectors.is_username_taken(username):
            raise forms.ValidationError("이미 사용 중인 아이디예요.")
        return username

    def clean_nickname(self):
        nickname = (self.cleaned_data.get("nickname") or "").strip()
        error = nickname_format_error(nickname)
        if error:
            raise forms.ValidationError(error)
        if selectors.is_nickname_taken(nickname):
            raise forms.ValidationError("이미 사용 중인 닉네임이에요.")
        return nickname

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise forms.ValidationError("이름을 2자 이상 입력해 주세요.")
        return name

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get("birth_date")
        if birth_date and (birth_date > date.today() or birth_date.year < 1900):
            raise forms.ValidationError("생년월일을 다시 확인해 주세요.")
        return birth_date

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if phone is None:
            raise forms.ValidationError("휴대폰 번호를 010-1234-5678 형식으로 입력해 주세요.")
        if selectors.is_phone_taken(phone):
            raise forms.ValidationError("이미 가입된 휴대폰 번호예요.")
        return phone

    def save(self, commit=True):  # pragma: no cover - 저장은 services.register_user 사용
        raise NotImplementedError("services.register_user 를 사용해 주세요.")


# ───────── 로그인 ─────────
class LoginForm(StyledFormMixin, AuthenticationForm):
    remember = forms.BooleanField(label="로그인 상태 유지", required=False, initial=True)

    error_messages = {
        "invalid_login": "아이디 또는 비밀번호를 다시 확인해 주세요.",
        "inactive": "이용이 제한된 계정이에요.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "아이디"
        self.fields["username"].widget.attrs.update({"placeholder": "아이디", "autocapitalize": "none"})
        self.fields["password"].label = "비밀번호"
        self.fields["password"].widget.attrs.update({"placeholder": "비밀번호"})


# ───────── 프로필 수정 ─────────
class ProfileForm(StyledFormMixin, forms.ModelForm):
    region = RegionChoiceField()
    avatar = forms.FileField(
        label="프로필 사진",
        required=False,
        help_text="jpg, png, gif, webp · 최대 10MB",
        widget=forms.FileInput(attrs={"accept": "image/*", "data-avatar-input": ""}),
    )
    remove_avatar = forms.BooleanField(label="기본 이미지로 바꾸기", required=False)

    class Meta:
        model = Profile
        fields = ("nickname", "region", "bio")
        labels = {"bio": "소개"}
        widgets = {
            "nickname": forms.TextInput(attrs=_check_attrs("nickname", autocomplete="nickname")),
            "bio": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": BIO_MAX_LENGTH,
                    "data-autoresize": "",
                    "placeholder": "이웃에게 나를 소개해 보세요. (예: 주말 오후에 거래 가능해요)",
                }
            ),
        }

    def clean_nickname(self):
        nickname = (self.cleaned_data.get("nickname") or "").strip()
        error = nickname_format_error(nickname)
        if error:
            raise forms.ValidationError(error)
        if selectors.is_nickname_taken(nickname, exclude_user_id=self.instance.user_id):
            raise forms.ValidationError("이미 사용 중인 닉네임이에요.")
        return nickname

    def clean_bio(self):
        bio = (self.cleaned_data.get("bio") or "").strip()
        if len(bio) > BIO_MAX_LENGTH:
            raise forms.ValidationError(f"소개는 {BIO_MAX_LENGTH}자까지 쓸 수 있어요.")
        return bio

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar:
            try:
                validate_image(avatar)
            except StorageError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return avatar
