"""신고 폼."""

from django import forms

from apps.core.forms import StyledFormMixin

from .models import Report

DETAIL_MAX_LENGTH = 1000


class ReportForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ("reason", "detail")
        labels = {"reason": "어떤 문제가 있나요?", "detail": "자세한 내용"}
        widgets = {
            "reason": forms.RadioSelect,  # 템플릿에서 카드형 라디오로 직접 렌더
            "detail": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": DETAIL_MAX_LENGTH,
                    "placeholder": "상황을 알려주시면 더 빠르게 확인할 수 있어요. (선택)",
                }
            ),
        }
        error_messages = {"reason": {"required": "신고 사유를 골라 주세요."}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # RadioSelect 의 빈 선택지(---------) 제거
        self.fields["reason"].choices = Report.Reason.choices

    def clean_detail(self):
        detail = (self.cleaned_data.get("detail") or "").strip()
        if len(detail) > DETAIL_MAX_LENGTH:
            raise forms.ValidationError(f"{DETAIL_MAX_LENGTH}자까지 쓸 수 있어요.")
        if self.cleaned_data.get("reason") == Report.Reason.ETC and not detail:
            raise forms.ValidationError("'기타'를 골랐다면 내용을 적어 주세요.")
        return detail
