"""accounts 뷰: 회원가입 · 로그인/로그아웃 · 마이페이지 · 프로필 수정 · 판매자 프로필."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.storage import StorageError
from apps.core.templatetags.poly_tags import display_name
from apps.moderation.models import Block
from apps.moderation.services import blocked_user_ids, is_blocked_between

from . import selectors, services
from .decorators import login_required
from .forms import (
    LoginForm,
    ProfileForm,
    SignUpForm,
    nickname_format_error,
    normalize_phone,
    username_format_error,
)

PAGE_SIZE = 20


# ───────── 공통 헬퍼 ─────────
def safe_next(request, fallback=None):
    """오픈 리다이렉트를 막고 next 파라미터를 돌려준다."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return resolve_url(fallback or settings.LOGIN_REDIRECT_URL)


def paginate(request, queryset, per_page=PAGE_SIZE):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def is_partial(request, target_id):
    """탭 전환처럼 특정 영역만 다시 그리는 HTMX 요청인지."""
    return (
        request.headers.get("HX-Request")
        and request.headers.get("HX-Target") == target_id
        and not request.headers.get("HX-History-Restore-Request")
    )


# ───────── 회원가입 ─────────
@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            user = services.register_user(
                username=data["username"],
                password=data["password1"],
                nickname=data["nickname"],
                name=data["name"],
                birth_date=data["birth_date"],
                phone=data["phone"],
                region=data["region"],
            )
        except services.AccountError as exc:
            form.add_error(None, str(exc))
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"{data['nickname']}님, 폴리마켓에 오신 걸 환영해요!")
            return redirect(safe_next(request))
    return render(request, "accounts/signup.html", {"form": form, "next": request.GET.get("next", "")})


# 실시간 확인 남용(계정 존재 여부 대량 조회) 방지: IP 당 5분에 60번
CHECK_LIMIT = 60
CHECK_WINDOW = 300


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else "") or request.META.get("REMOTE_ADDR", "")


def _check_throttled(request) -> bool:
    """간단한 캐시 카운터. 한도를 넘으면 True."""
    key = f"dupcheck:{_client_ip(request)}"
    cache.add(key, 0, CHECK_WINDOW)
    try:
        count = cache.incr(key)
    except ValueError:  # 그 사이 만료됨
        cache.set(key, 1, CHECK_WINDOW)
        count = 1
    return count > CHECK_LIMIT


@require_GET
def check_duplicate(request):
    """회원가입 입력 중 실시간 중복 확인 (HTMX partial).

    휴대폰 번호는 개인정보라 형식만 확인하고, 가입 여부는 제출할 때만 알려 준다.
    """
    result = {"ok": None, "message": ""}
    if _check_throttled(request):
        result = {"ok": None, "message": "잠시 후 다시 확인해 주세요."}
    elif "username" in request.GET:
        value = request.GET["username"].strip()
        if value:
            error = username_format_error(value)
            if error:
                result = {"ok": False, "message": error}
            elif selectors.is_username_taken(value):
                result = {"ok": False, "message": "이미 사용 중인 아이디예요."}
            else:
                result = {"ok": True, "message": "사용할 수 있는 아이디예요."}
    elif "nickname" in request.GET:
        value = request.GET["nickname"].strip()
        if value:
            error = nickname_format_error(value)
            exclude = request.user.pk if request.user.is_authenticated else None
            if error:
                result = {"ok": False, "message": error}
            elif selectors.is_nickname_taken(value, exclude_user_id=exclude):
                result = {"ok": False, "message": "이미 사용 중인 닉네임이에요."}
            else:
                result = {"ok": True, "message": "멋진 닉네임이에요!"}
    elif "phone" in request.GET:
        value = request.GET["phone"].strip()
        if value:
            phone = normalize_phone(value)
            if phone is None:
                result = {"ok": False, "message": "010-1234-5678 형식으로 입력해 주세요."}
            else:
                result = {"ok": True, "message": "올바른 번호 형식이에요."}
    return render(request, "accounts/partials/duplicate_check.html", result)


# ───────── 로그인 / 로그아웃 ─────────
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(safe_next(request))
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        if not form.cleaned_data.get("remember"):
            request.session.set_expiry(0)  # 브라우저를 닫으면 로그아웃
        messages.success(request, f"{display_name(user)}님, 다시 만나서 반가워요.")
        return redirect(safe_next(request))
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "로그아웃했어요. 또 만나요!")
    return redirect(settings.LOGOUT_REDIRECT_URL)


# ───────── 마이페이지 ─────────
@login_required
@require_GET
def mypage(request):
    user = request.user
    profile = services.ensure_profile(user)
    tab = request.GET.get("tab", "selling")
    if tab not in dict(selectors.MYPAGE_TABS):
        tab = "selling"

    hidden = blocked_user_ids(user)
    page_obj = None
    if tab == "selling":
        page_obj = paginate(request, selectors.selling_products(user))
    elif tab == "sold":
        page_obj = paginate(request, selectors.sold_products(user))
    elif tab == "bought":
        page_obj = paginate(request, selectors.bought_products(user, hidden))
    elif tab == "wishlist":
        page_obj = paginate(request, selectors.wishlist_products(user, hidden))
    elif tab == "recent":
        page_obj = paginate(request, selectors.recent_products(user, hidden))
    else:
        page_obj = paginate(request, selectors.received_reviews(user))

    counts = selectors.mypage_counts(user, hidden)
    context = {
        "profile": profile,
        "tab": tab,
        "tabs": selectors.build_tabs(selectors.MYPAGE_TABS, counts, tab),
        "page_obj": page_obj,
        "counts": counts,
        "summary": selectors.review_summary(user),
    }
    if is_partial(request, "mypage-panel"):
        return render(request, "accounts/partials/mypage_panel.html", context)
    return render(request, "accounts/mypage.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    profile = services.ensure_profile(request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.update_profile(
                profile,
                nickname=data["nickname"],
                region=data["region"],
                bio=data["bio"],
                avatar_file=data.get("avatar"),
                remove_avatar=data.get("remove_avatar", False),
            )
        except StorageError as exc:
            form.add_error("avatar", str(exc))
        except services.AccountError as exc:
            form.add_error("nickname", str(exc))
        else:
            messages.success(request, "프로필을 저장했어요.")
            return redirect("accounts:mypage")
        profile.refresh_from_db()  # 실패 시 화면의 현재 아바타는 원래 값으로
    return render(request, "accounts/profile_edit.html", {"form": form, "profile": profile})


# ───────── 판매자(공개) 프로필 ─────────
@require_GET
def seller_profile(request, username):
    seller = selectors.public_user(username)
    if seller is None:
        raise Http404("사용자를 찾을 수 없어요.")
    profile = getattr(seller, "profile", None)  # 관리자 등 프로필 없는 사용자도 있음

    viewer = request.user
    is_me = viewer.is_authenticated and viewer.pk == seller.pk
    i_blocked = (
        viewer.is_authenticated and not is_me and Block.objects.filter(blocker=viewer, blocked=seller).exists()
    )
    blocked = i_blocked or (viewer.is_authenticated and not is_me and is_blocked_between(viewer, seller))

    tab = request.GET.get("tab", "selling")
    if tab not in dict(selectors.SELLER_TABS):
        tab = "selling"

    counts = selectors.product_counts(seller)
    summary = selectors.review_summary(seller)
    counts["reviews"] = summary["count"]

    page_obj = None
    if not blocked:
        if tab == "selling":
            page_obj = paginate(request, selectors.selling_products(seller))
        elif tab == "sold":
            page_obj = paginate(request, selectors.sold_products(seller))
        else:
            page_obj = paginate(request, selectors.received_reviews(seller))

    context = {
        "seller": seller,
        "profile": profile,
        "is_me": is_me,
        "i_blocked": i_blocked,
        "blocked": blocked,
        "tab": tab,
        "tabs": selectors.build_tabs(selectors.SELLER_TABS, counts, tab),
        "counts": counts,
        "summary": summary,
        "page_obj": page_obj,
    }
    if is_partial(request, "seller-panel"):
        return render(request, "accounts/partials/seller_panel.html", context)
    return render(request, "accounts/seller_profile.html", context)
