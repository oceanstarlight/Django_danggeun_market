"""foundation 단계 임시 뷰.

각 앱 담당자가 실제 뷰를 만들기 전까지 {% url %} 이 깨지지 않도록
URL 이름만 살려두는 용도. 실제 구현으로 교체되면 사용처가 사라진다.
"""

from django.http import HttpResponse
from django.shortcuts import render


def placeholder(url_name):
    """'준비 중' 화면을 돌려주는 뷰 함수를 만든다."""

    def view(request, *args, **kwargs):
        # HTMX 조각 요청(알림 배지 polling 등)은 화면을 건드리지 않도록 204
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204)
        return render(request, "core/placeholder.html", {"url_name": url_name})

    view.__name__ = url_name.replace(":", "_")
    view.is_placeholder = True
    return view
