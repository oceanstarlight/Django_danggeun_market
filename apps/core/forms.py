from django import forms
from django.forms.widgets import Input


class StyledFormMixin:
    """위젯 타입별로 디자인 시스템 CSS 클래스를 자동으로 붙여준다.

    사용: class MyForm(StyledFormMixin, forms.ModelForm): ...
    이미 지정된 class 속성은 유지하고 앞에 기본 클래스를 덧붙인다.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            css = self._css_class_for(widget)
            if css:
                existing = widget.attrs.get("class", "")
                if css not in existing.split():
                    widget.attrs["class"] = f"{css} {existing}".strip()
        # 주의: 여기서 self.errors 를 읽으면 하위 폼이 __init__ 에서 queryset 등을 바꾸기 전에
        # 검증이 끝나 버린다 → aria-invalid 표시는 full_clean() 이후에 한다.

    def full_clean(self):
        super().full_clean()
        # 에러가 있는 필드는 aria-invalid 표시
        for name in self._errors or {}:
            if name in self.fields:
                self.fields[name].widget.attrs["aria-invalid"] = "true"

    @staticmethod
    def _css_class_for(widget):
        if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            return "checkbox"
        if isinstance(widget, forms.Textarea):
            return "textarea"
        if isinstance(widget, (forms.Select, forms.SelectMultiple)):
            return "select"
        if isinstance(widget, forms.HiddenInput):
            return ""
        if isinstance(widget, Input):  # TextInput, EmailInput, FileInput, DateInput 등
            return "input"
        return ""
