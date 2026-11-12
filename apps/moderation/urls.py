from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("report/product/<int:pk>/", views.report_product, name="report_product"),
    path("report/user/<str:username>/", views.report_user, name="report_user"),
    path("block/<str:username>/", views.block_toggle, name="block_toggle"),  # POST
    path("blocks/", views.block_list, name="block_list"),
]
