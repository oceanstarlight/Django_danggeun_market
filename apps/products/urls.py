from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("", views.product_list, name="list"),
    path("new/", views.product_create, name="create"),
    path("<int:pk>/", views.product_detail, name="detail"),
    path("<int:pk>/edit/", views.product_update, name="update"),
    path("<int:pk>/delete/", views.product_delete, name="delete"),
    path("<int:pk>/wishlist/", views.wishlist_toggle, name="wishlist_toggle"),  # POST
    path("<int:pk>/status/", views.status_change, name="status_change"),  # POST
]
