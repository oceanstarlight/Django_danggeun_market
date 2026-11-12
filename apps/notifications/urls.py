from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("dropdown/", views.dropdown, name="dropdown"),  # HTMX partial
    path("read-all/", views.read_all, name="read_all"),  # POST
    path("badge/", views.badge, name="badge"),  # HTMX partial
    path("<int:pk>/go/", views.go, name="go"),
]
