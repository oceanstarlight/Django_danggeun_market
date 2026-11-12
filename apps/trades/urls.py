from django.urls import path

from . import views

app_name = "trades"

urlpatterns = [
    path("<int:product_id>/complete/", views.complete, name="complete"),
    path("<int:product_id>/review/", views.review_create, name="review_create"),
]
