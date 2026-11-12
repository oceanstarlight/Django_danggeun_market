from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import render


def health(request):
    """Render 헬스체크용 (/state/)."""
    return HttpResponse("server OK", content_type="text/plain; charset=utf-8")


def styleguide(request):
    """디자인 시스템 스타일가이드 (DEBUG 에서만 열림, /dev/styleguide/)."""
    if not settings.DEBUG:
        raise Http404
    from apps.products.models import Product

    sample_products = (
        Product.objects.select_related("region", "category")
        .prefetch_related("images")[:5]
    )
    return render(request, "components/_styleguide.html", {"sample_products": sample_products})
