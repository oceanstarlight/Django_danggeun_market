# 컨트롤러 역할을 하는 뷰(View) 정의


from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)

from django.contrib.auth import (
    authenticate,
    login,
    logout,
)

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.contrib import messages

from .models import (
    Product,
    Wishlist,
    ChatRoom,
)

from .forms import ProductForm
from .storage import upload_product_image
from .forms import SignUpForm

#메인 리다이렉트
def main(request):
    return render(request, "market/main.html")

#회원가입
def signup(request):

    if request.user.is_authenticated:

        return redirect(
            "main"
        )


    if request.method == "POST":

        form = SignUpForm(
            request.POST
        )

        if form.is_valid():

            user = form.save()

            login(
                request,
                user
            )

            return redirect(
                "main"
            )

    else:

        form = SignUpForm()


    return render(
        request,
        "market/signup.html",
        {
            "form": form
        }
    )


#로그인
def login_view(request):

    if request.user.is_authenticated:

        return redirect(
            "main"
        )


    if request.method == "POST":

        username = request.POST.get(
            "username"
        )

        password = request.POST.get(
            "password"
        )


        user = authenticate(
            request,
            username=username,
            password=password
        )


        if user is not None:

            login(
                request,
                user
            )

            return redirect(
                "main"
            )


        messages.error(
            request,
            "아이디 또는 비밀번호가 올바르지 않습니다."
        )


    return render(
        request,
        "market/login.html"
    )

#로그아웃
def logout_view(request):

    if request.method == "POST":

        logout(request)

    return redirect(
        "main"
    )

# 상품 목록
def product_list(request):

    products = (
        Product.objects
        .select_related("seller")
        .all()
    )

    return render(
        request,
        "market/product_list.html",
        {
            "products": products
        }
    )

# 상품 등록
@login_required
def product_create(request):

    if request.method == "POST":

        form = ProductForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            product = form.save(
                commit=False
            )

            product.seller = request.user

            image = form.cleaned_data.get(
                "image"
            )

            if image:

                product.image_url = (
                    upload_product_image(
                        image,
                        request.user.id
                    )
                )

            product.save()

            return redirect(
                "product_detail",
                product_id=product.id
            )

    else:

        form = ProductForm()

    return render(
        request,
        "market/product_form.html",
        {
            "form": form,
            "page_title": "중고상품 등록",
        }
    )

# 상품 상세 + 조회수
def product_detail(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    Product.objects.filter(
        id=product.id
    ).update(
        view_count=F("view_count") + 1
    )

    product.refresh_from_db(
        fields=["view_count"]
    )

    is_wished = False

    if request.user.is_authenticated:

        is_wished = (
            Wishlist.objects.filter(
                user=request.user,
                product=product
            ).exists()
        )

    return render(
        request,
        "market/product_detail.html",
        {
            "product": product,
            "is_wished": is_wished,
        }
    )

# 상품 수정
@login_required
def product_update(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if product.seller != request.user:
        raise PermissionDenied

    if request.method == "POST":

        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product
        )

        if form.is_valid():

            product = form.save(
                commit=False
            )

            image = form.cleaned_data.get(
                "image"
            )

            if image:

                product.image_url = (
                    upload_product_image(
                        image,
                        request.user.id
                    )
                )

            product.save()

            return redirect(
                "product_detail",
                product_id=product.id
            )

    else:

        form = ProductForm(
            instance=product
        )

    return render(
        request,
        "market/product_form.html",
        {
            "form": form,
            "page_title": "상품 수정",
        }
    )

# 상품 삭제
@login_required
def product_delete(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if product.seller != request.user:
        raise PermissionDenied

    if request.method == "POST":

        product.delete()

        return redirect(
            "product_list"
        )

    return render(
        request,
        "market/product_delete.html",
        {
            "product": product
        }
    )

# 찜하기/취소
@login_required
def wishlist_toggle(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if product.seller == request.user:

        return redirect(
            "product_detail",
            product_id=product.id
        )

    if request.method == "POST":

        wishlist, created = (
            Wishlist.objects
            .get_or_create(
                user=request.user,
                product=product
            )
        )

        if not created:
            wishlist.delete()

    return redirect(
        "product_detail",
        product_id=product.id
    )

# 채팅 시작
@login_required
def chat_start(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if product.seller == request.user:

        return redirect(
            "product_detail",
            product_id=product.id
        )

    room, created = (
        ChatRoom.objects
        .get_or_create(
            product=product,
            buyer=request.user,
            defaults={
                "seller": product.seller
            }
        )
    )

    return redirect(
        "chat_room",
        room_id=room.id
    )

# 내 채팅 목록
@login_required
def chat_list(request):

    rooms = (
        ChatRoom.objects
        .filter(
            Q(seller=request.user)
            |
            Q(buyer=request.user)
        )
        .select_related(
            "product",
            "seller",
            "buyer"
        )
        .order_by("-created_at")
    )

    return render(
        request,
        "market/chat_list.html",
        {
            "rooms": rooms
        }
    )

# 채팅방 화면 View
@login_required
def chat_room(request, room_id):

    room = get_object_or_404(
        ChatRoom.objects.select_related(
            "product",
            "seller",
            "buyer"
        ),
        id=room_id
    )

    if (
        request.user != room.seller
        and
        request.user != room.buyer
    ):
        raise PermissionDenied

    chat_messages = (
        room.messages
        .select_related("sender")
        .all()
    )

    return render(
        request,
        "market/chat_room.html",
        {
            "room": room,
            "chat_messages": chat_messages,
        }
    )