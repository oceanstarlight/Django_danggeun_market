from django import forms

from apps.core.forms import StyledFormMixin

from . import services


class ReviewForm(StyledFormMixin, forms.Form):
    """거래 후기 폼. 별점/태그 위젯은 템플릿에서 직접 그린다."""

    rating = forms.TypedChoiceField(
        label="별점",
        coerce=int,
        choices=[(n, services.RATING_LABELS[n]) for n in (5, 4, 3, 2, 1)],
        widget=forms.RadioSelect,
        error_messages={"required": "별점을 선택해 주세요.", "invalid_choice": "별점을 다시 선택해 주세요."},
    )
    good_tags = forms.MultipleChoiceField(
        label="좋았던 점", required=False, widget=forms.CheckboxSelectMultiple
    )
    bad_tags = forms.MultipleChoiceField(
        label="아쉬웠던 점", required=False, widget=forms.CheckboxSelectMultiple
    )
    content = forms.CharField(
        label="후기",
        required=False,
        max_length=services.REVIEW_MAX_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "따뜻한 후기는 이웃에게 큰 힘이 돼요.",
                "data-autoresize": "",
            }
        ),
        error_messages={"max_length": f"후기는 {services.REVIEW_MAX_LENGTH}자까지 쓸 수 있어요."},
    )

    def __init__(self, *args, reviewee_is_seller=True, **kwargs):
        super().__init__(*args, **kwargs)
        good, bad = services.manner_tag_choices(reviewee_is_seller)
        self.fields["good_tags"].choices = [(t, t) for t in good]
        self.fields["bad_tags"].choices = [(t, t) for t in bad]
        self.fields["good_tags"].error_messages["invalid_choice"] = "선택할 수 없는 태그가 있어요."
        self.fields["bad_tags"].error_messages["invalid_choice"] = "선택할 수 없는 태그가 있어요."

    def rating_options(self):
        """별점 위젯용 선택지 (5 → 1 순서: CSS row-reverse 로 1 → 5 로 보인다)."""
        current = str(self["rating"].value() or "")
        options = []
        for value, label in self.fields["rating"].choices:
            delta = services.RATING_DELTA[value]
            if delta > 0:
                effect = f"매너온도 +{delta}°C"
            elif delta < 0:
                effect = f"매너온도 {delta}°C"
            else:
                effect = "매너온도 변화 없음"
            options.append(
                {
                    "value": value,
                    "label": label,
                    "caption": f"{label} · {effect}",
                    "checked": current == str(value),
                    "id": f"id_rating_{value}",
                }
            )
        return options

    def clean(self):
        cleaned = super().clean()
        # 서비스에는 좋았던 점 + 아쉬웠던 점을 한 목록으로 넘긴다
        cleaned["manner_tags"] = list(cleaned.get("good_tags") or []) + list(cleaned.get("bad_tags") or [])
        return cleaned
