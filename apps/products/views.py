"""상품 뷰 (홈/목록/상세/등록/수정/삭제/찜/상태 변경).

뷰는 요청 파싱 · 권한 · 응답만 담당하고 조회는 selectors, 쓰기는 services 를 쓴다.
"""

import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts import regions as region_lookup
from apps.core.storage import StorageError
from apps.moderation.services import is_blocked_between

from . import selectors, services
from .forms import MAX_IMAGES, ProductFilterForm, ProductForm
from .models import Category, Product

VIEWED_SESSION_KEY = "viewed_products"
VIEWED_SESSION_LIMIT = 200


# ───────────────────────── 공용 헬퍼 ─────────────────────────


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def login_required_htmx(view):
    """login_required 와 같지만 HTMX 요청이면 HX-Redirect 로 로그인 페이지로 보낸다.

    (일반 302 는 htmx 가 따라가서 로그인 화면을 버튼 자리에 붙여 버린다)
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view(request, *args, **kwargs)
        if _is_htmx(request):
            next_url = request.headers.get("HX-Current-URL") or request.get_full_path()
            login_url = f"{reverse('accounts:login')}?next={_path_only(next_url)}"
            response = HttpResponse(status=204)
            response["HX-Redirect"] = login_url
            return response
        return redirect_to_login(request.get_full_path())

    return wrapper


def _path_only(url):
    """HX-Current-URL(절대 URL)에서 경로+쿼리만 남긴다."""
    from urllib.parse import quote, urlsplit

    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return quote(path, safe="/?=&")


def _safe_next(request, fallback):
    """POST/GET 의 next 가 같은 사이트 경로일 때만 사용."""
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return fallback


def _toast_header(response, message, level="success"):
    # 헤더는 ASCII 만 안전 → 한글은 \uXXXX 로 이스케이프 (JSON.parse 가 복원)
    response["HX-Trigger"] = json.dumps({"showToast": {"message": message, "level": level}})
    return response


def _get_owned_product(request, pk, allow_staff=False):
    """본인 상품만 (없으면 404, 남의 상품이면 403)."""
    product = get_object_or_404(Product.objects.select_related("seller", "category", "region"), pk=pk)
    if product.seller_id != request.user.pk and not (allow_staff and request.user.is_staff):
        raise PermissionDenied("내 상품만 관리할 수 있어요.")
    return product


# ───────────────────────── 홈 ─────────────────────────


def home(request):
    """홈: 검색 히어로 · 카테고리 · 내 동네 최신 상품 · 인기 상품 TOP · 최근 본 상품."""
    user = request.user
    my_region = selectors.user_region(user)
    local_products = selectors.latest_products(user, region=my_region, limit=10)
    context = {
        "categories": Category.objects.all(),
        "my_region": my_region,
        "local_products": local_products,
        "popular_products": selectors.popular_products(user, limit=10),
        "recent_products": selectors.recent_viewed_products(user, limit=12),
        "suggested_keywords": ["아이폰", "자전거", "캠핑", "책상", "에어팟", "유모차", "닌텐도"],
    }
    return render(request, "core/home.html", context)


# ───────────────────────── 목록 / 검색 ─────────────────────────


def product_list(request):
    """목록/검색/필터/정렬. HTMX 요청이면 그리드 partial 만 돌려준다."""
    params = ProductFilterForm(request.GET).params()
    raw_region = request.GET.get("region")
    sido = request.GET.get("sido")  # 3단 동네 select 로 제출하면 항상 있음 (빈 값 = 전체 지역)
    if not raw_region and sido is None and params["q"]:
        # 상단 검색창(동네 선택 없음)으로 찾을 땐 전체 지역에서 보여줘요
        raw_region = "all"
    region_filter = selectors.resolve_region_filter(
        request.user, region=raw_region, sido=sido, sigungu=request.GET.get("sigungu", "")
    )
    category = selectors.category_by_slug(params["category"])

    queryset = selectors.search_products(
        request.user,
        q=params["q"],
        category=category,
        region=region_filter.region,
        sido=region_filter.sido,
        sigungu=region_filter.sigungu,
        status=params["status"],
        sort=params["sort"],
    )
    page_obj = Paginator(queryset, selectors.PAGE_SIZE).get_page(request.GET.get("page"))
    my_region = selectors.user_region(request.user)

    context = {
        "page_obj": page_obj,
        "products": page_obj.object_list,
        "q": params["q"],
        "current_category": category,
        "current_region": region_filter.region,
        "region_filter": region_filter,
        "region_value": region_filter.value,
        "status_value": params["status"],
        "sort_value": params["sort"],
        "sort_choices": ProductFilterForm.SORT_CHOICES,
        "my_region": my_region,
        "is_append": page_obj.number > 1,
    }
    if _is_htmx(request):
        return render(request, "products/partials/product_grid.html", context)

    sel_sido, sel_sigungu, sel_region = region_filter.selection
    region_params = region_filter.query_params()
    context.update(
        {
            "categories": Category.objects.all(),
            "region_select": region_lookup.build_select_context(
                id_prefix="filter-region",
                names={"sido": "sido", "sigungu": "sigungu", "dong": "region"},
                sido=sel_sido,
                sigungu=sel_sigungu,
                region=sel_region,
                mode="filter",
                legend="동네",
                keep=my_region,  # 내 동네가 예전 시드 행(코드 없음)이어도 목록에 보이게 (필터 기준과 같게)
            ),
            "reset_url": reverse("products:list") + (f"?{urlencode(region_params)}" if region_params else ""),
            "has_filters": bool(params["q"] or category or params["status"] != "all" or params["sort"] != "latest"),
        }
    )
    return render(request, "products/product_list.html", context)


# ───────────────────────── 상세 ─────────────────────────


def product_detail(request, pk):
    product = selectors.get_product_for_detail(pk, request.user)
    if product is None:
        raise Http404("상품을 찾을 수 없어요.")

    user = request.user
    is_owner = user.is_authenticated and user.pk == product.seller_id
    blocked = user.is_authenticated and not is_owner and is_blocked_between(user, product.seller)

    # 같은 세션에서 새로고침할 때마다 조회수가 오르지 않게
    viewed = request.session.get(VIEWED_SESSION_KEY, [])
    first_view = product.pk not in viewed
    services.record_view(product, user if user.is_authenticated else None, count=first_view)
    if first_view and not is_owner:
        request.session[VIEWED_SESSION_KEY] = (viewed + [product.pk])[-VIEWED_SESSION_LIMIT:]

    images = list(product.images.all())
    context = {
        "product": product,
        "images": images,
        "is_owner": is_owner,
        "is_blocked": blocked,
        "is_wished": selectors.is_wished(user, product),
        "wish_count": product.wish_count,
        "chat_room": None if blocked else selectors.user_chat_room(user, product),
        "other_products": selectors.seller_other_products(product, user, limit=6),
        "seller_stats": selectors.seller_stats(product.seller),
        "fraud_analysis": _fraud_analysis(product),
        "status_choices": Product.Status.choices,
        "review_url": _review_url(product, user),
    }
    return render(request, "products/product_detail.html", context)


def _fraud_analysis(product):
    """사기 분석 결과 (아직 없으면 None). select_related 로 이미 불러와 있다."""
    try:
        return product.fraud_analysis
    except ObjectDoesNotExist:
        return None


def _review_url(product, user):
    """거래완료 상품의 판매자/구매자가 아직 후기를 안 썼으면 후기 작성 URL."""
    if product.status != Product.Status.SOLD or not product.buyer_id or not user.is_authenticated:
        return None
    if user.pk not in (product.seller_id, product.buyer_id):
        return None
    try:
        from apps.trades.models import Review

        if Review.objects.filter(product=product, reviewer=user).exists():
            return None
    except Exception:  # noqa: BLE001 - trades 앱 미완성 시에도 상세는 열려야 함
        return None
    return reverse("trades:review_create", args=[product.pk])


# ───────────────────────── 등록 / 수정 / 삭제 ─────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            product = services.create_product(request.user, form.product_data(), form.cleaned_data["images"])
        except StorageError as exc:
            form.add_error("images", str(exc))
        else:
            messages.success(request, "상품을 등록했어요.")
            return redirect("products:detail", pk=product.pk)
    elif request.method == "POST":
        messages.error(request, "입력한 내용을 다시 확인해 주세요.")
    return render(request, "products/product_form.html", _form_context(form))


@login_required
@require_http_methods(["GET", "POST"])
def product_update(request, pk):
    product = _get_owned_product(request, pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_product(
                product,
                form.product_data(),
                new_images=form.cleaned_data["images"],
                remove_images=form.cleaned_data["remove_images"],
            )
        except StorageError as exc:
            form.add_error("images", str(exc))
        else:
            messages.success(request, "상품 정보를 수정했어요.")
            return redirect("products:detail", pk=product.pk)
    elif request.method == "POST":
        messages.error(request, "입력한 내용을 다시 확인해 주세요.")
    return render(request, "products/product_form.html", _form_context(form, product))


def _form_context(form, product=None):
    return {
        "form": form,
        "product": product,
        "is_edit": product is not None,
        "max_images": MAX_IMAGES,
        "existing_images": form.existing_images,
        "removed_ids": form.removed_image_ids,
    }


@login_required
@require_http_methods(["GET", "POST"])
def product_delete(request, pk):
    """GET: 확인 화면, POST: 삭제. 판매자 본인(또는 스태프)만."""
    product = _get_owned_product(request, pk, allow_staff=True)
    if request.method == "POST":
        title = product.title
        services.delete_product(product)
        messages.success(request, f"'{title}' 상품을 삭제했어요.")
        return redirect("accounts:mypage")
    return render(request, "products/product_confirm_delete.html", {"product": product})


# ───────────────────────── 찜 / 상태 변경 ─────────────────────────


@login_required_htmx
@require_POST
def wishlist_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    detail_url = reverse("products:detail", args=[product.pk])

    error = None
    if is_blocked_between(request.user, product.seller):
        error = "차단 관계인 사용자의 상품은 찜할 수 없어요."
    else:
        try:
            wished = services.toggle_wishlist(request.user, product)
        except services.ProductActionError as exc:
            error = str(exc)

    if _is_htmx(request):
        if error:
            return _toast_header(HttpResponse(status=204), error, "danger")
        wish_count = product.wishlists.count()
        variant = request.POST.get("variant", "default")
        html = render_to_string(
            "products/partials/wishlist_response.html",
            {"product": product, "is_wished": wished, "wish_count": wish_count, "variant": variant},
            request=request,
        )
        return _toast_header(HttpResponse(html), "찜했어요" if wished else "찜을 해제했어요")

    if error:
        messages.error(request, error)
    else:
        messages.success(request, "찜했어요" if wished else "찜을 해제했어요")
    return redirect(_safe_next(request, detail_url))


@login_required_htmx
@require_POST
def status_change(request, pk):
    """판매 상태 변경 (판매중/예약중). 거래완료는 trades:complete 로 보낸다."""
    product = _get_owned_product(request, pk)
    detail_url = reverse("products:detail", args=[product.pk])
    status = request.POST.get("status", "")
    next_url = _safe_next(request, detail_url)

    if status == Product.Status.SOLD:
        if product.status == Product.Status.SOLD:
            target = next_url
        else:
            messages.info(request, "거래한 구매자를 선택해 주세요.")
            target = reverse("trades:complete", args=[product.pk])
    else:
        try:
            changed = services.change_status(product, status)
        except services.ProductActionError as exc:
            messages.error(request, str(exc))
        else:
            if changed:
                # '판매중'/'예약중' 모두 받침이 있어서 '으로'
                messages.success(request, f"판매 상태를 '{product.get_status_display()}'으로 바꿨어요.")
        target = next_url

    if _is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
        return response
    return redirect(target)
