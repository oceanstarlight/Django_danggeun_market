from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_list, name="list"),
    path("<int:room_id>/", views.chat_room, name="room"),
    path("start/<int:product_id>/", views.chat_start, name="start"),
    path("<int:room_id>/read/", views.mark_read, name="mark_read"),  # POST
]
