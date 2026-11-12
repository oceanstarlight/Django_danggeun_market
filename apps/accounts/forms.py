"""회원가입 / 로그인 / 프로필 수정 폼."""

import re
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q
from django.urls import reverse_lazy
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from apps.core.forms import StyledFormMixin
from apps.core.storage import StorageError, validate_image

from . import regions, selectors
from .models import Profile, Region

User = get_user_model()

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{4,20}$")
# 띄어쓰기는 가운데에만 (앞뒤 공백·연속 공백은 normalize_nickname 이 정리)
NICKNAME_RE = re.compile(r"^[가-힣a-zA-Z0-9_](?:[가-힣a-zA-Z0-9_ ]{0,18})[가-힣a-zA-Z0-9_]$")
PHONE_RE = re.compile(r"^01[016789]\d{7,8}$")

BIO_MAX_LENGTH = 300


# ───────── 형식 검사 (폼 + 실시간 중복 확인에서 함께 사용) ─────────
def username_format_error(value: str) -> str | None:
    if not USERNAME_RE.match(value or ""):
        return "아이디는 영문, 숫자, 밑줄(_)로 4~20자 입력해 주세요."
    return None


def normalize_nickname(value: str) -> str:
    """앞뒤 공백을 지우고 연속 공백(탭·줄바꿈 포함)을 한 칸으로 합친다."""
    return re.sub(r"\s+", " ", value or "").strip()


def nickname_format_error(value: str) -> str | None:
    if not NICKNAME_RE.match(value or "") or "  " in value:
        return "닉네임은 한글, 영문, 숫자, 밑줄(_), 띄어쓰기로 2~20자 입력해 주세요."
    return None


def normalize_phone(value: str) -> str | None:
    """숫자만 남겨 '010-1234-5678' 형식으로 바꾼다. 형식이 틀리면 None."""
    digits = re.sub(r"\D", "", value or "")
    if not PHONE_RE.match(digits):
        return None
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"


# ───────── 동네 선택 (시/도 → 시/군/구 → 읍/면/동) ─────────
class RegionValue(str):
    """제출된 Region pk 문자열 + 함께 고른 시/도·시/군/구 (검증 실패 후 다시 그릴 때 쓰려고)."""

    def __new__(cls, value="", sido="", sigungu=""):
        obj = super().__new__(cls, value or "")
        obj.sido = regions.clean_param(sido)
        obj.sigungu = regions.clean_param(sigungu)
        return obj


class RegionSelect(forms.Widget):
    """select 3개(시/도 · 시/군/구 · 읍/면/동)로 그리는 위젯. 제출 값은 마지막 select 의 Region pk.

    이름: <name>_sido, <name>_sigungu, <name>(= pk). 렌더는 templates/components/region_select.html.
    """

    template_name = "components/region_select.html"

    def __init__(self, attrs=None, mode="form"):
        super().__init__(attrs)
        self.mode = mode

    def subwidget_names(self, name):
        return {"sido": f"{name}_sido", "sigungu": f"{name}_sigungu", "dong": name}

    def value_from_datadict(self, data, files, name):
        names = self.subwidget_names(name)
        return RegionValue(data.get(names["dong"], ""), data.get(names["sido"], ""), data.get(names["sigungu"], ""))

    def value_omitted_from_data(self, data, files, name):
        return not any(key in data for key in self.subwidget_names(name).values())

    def id_for_label(self, id_):
        return f"{id_}_sido" if id_ else id_

    def selection(self, value):
        """value(pk / RegionValue / Region) → (sido, sigungu, Region|None).

        제출한 시/도·시/군/구와 맞지 않는 pk 면(RegionChoiceField 가 에러로 돌려보냄) 고른 위 단계를 그대로 보여준다.
        """
        region = regions.region_by_pk(value)
        sido, sigungu = getattr(value, "sido", ""), getattr(value, "sigungu", "")
        if region is not None and not region_matches(region, sido, sigungu):
            region = None
        if region is not None:
            return region.sido, region.sigungu, region
        return sido, sigungu, None

    def get_context(self, name, value, attrs):
        attrs = self.build_attrs(self.attrs, attrs)
        sido, sigungu, region = self.selection(value)
        return {
            "region_select": regions.build_select_context(
                id_prefix=attrs.get("id") or f"id_{name}",
                names=self.subwidget_names(name),
                sido=sido,
                sigungu=sigungu,
                region=region,
                mode=self.mode,
                attrs=attrs,
            )
        }

    def render(self, name, value, attrs=None, renderer=None):
        # 프로젝트 templates/ 의 컴포넌트를 그대로 쓰려고 폼 렌더러 대신 템플릿 로더로 그린다
        return mark_safe(render_to_string(self.template_name, self.get_context(name, value, attrs)))


def region_matches(region, sido="", sigungu=""):
    """함께 제출된 위 단계(비어 있으면 검사 안 함)가 region 과 맞는지."""
    if sido and region.sido != sido:
        return False
    if sigungu and region.sigungu != sigungu:
        return False
    return True


class RegionChoiceField(forms.ModelChoiceField):
    """시/도 → 시/군/구 → 읍/면/동 을 차례로 고르는 동네 필드. cleaned_data 는 Region.

    새로 고를 수 있는 건 행정동 코드가 있는 행뿐이에요. 예전 시드 행(code 없음)은 폼이 allow() 로 허락한
    값(지금 내 동네, 수정 중인 상품의 동네)일 때만 통과해요.
    """

    widget = RegionSelect

    def __init__(self, **kwargs):
        kwargs.setdefault("queryset", Region.objects.filter(code__isnull=False))
        kwargs.setdefault("empty_label", None)
        kwargs.setdefault("label", "내 동네")
        messages_ = {
            "required": "동네를 선택해 주세요.",
            "incomplete": "읍/면/동까지 선택해 주세요.",
            "invalid_choice": "목록에서 동네를 골라 주세요.",
            "mismatch": "고른 시/도·시/군/구와 읍/면/동이 맞지 않아요. 다시 골라 주세요.",
        }
        messages_.update(kwargs.pop("error_messages", None) or {})
        kwargs["error_messages"] = messages_
        super().__init__(**kwargs)

    def clean(self, value):
        if self.required and not str(value or "").strip() and getattr(value, "sido", ""):
            # 시/도(·시/군/구)까지만 고르고 멈춘 경우
            raise forms.ValidationError(self.error_messages["incomplete"], code="required")
        if str(value or "").strip() and regions.parse_pk(value) is None:
            # 'abc', '²', NUL 이 섞인 값 등 → 쿼리 없이 같은 안내
            raise forms.ValidationError(self.error_messages["invalid_choice"], code="invalid_choice")
        region = super().clean(value)
        if region is not None and not region_matches(
            region, getattr(value, "sido", ""), getattr(value, "sigungu", "")
        ):
            raise forms.ValidationError(self.error_messages["mismatch"], code="mismatch")
        return region

    def allow(self, *allowed):
        """코드가 없는 예전 행이라도 이 Region(또는 pk)들은 그대로 받는다 (지금 값 유지용)."""
        pks = {getattr(r, "pk", r) for r in allowed if r}
        if pks:
            self.queryset = Region.objects.filter(Q(code__isnull=False) | Q(pk__in=pks))


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
        nickname = normalize_nickname(self.cleaned_data.get("nickname"))
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 지금 내 동네가 예전 시드 행이어도 바꾸지 않고 저장할 수 있게
        self.fields["region"].allow(self.instance.region_id)

    def clean_nickname(self):
        nickname = normalize_nickname(self.cleaned_data.get("nickname"))
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
