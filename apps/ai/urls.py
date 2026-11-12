from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("describe/", views.describe, name="describe"),  # POST multipart
    path("recognize/", views.recognize, name="recognize"),  # POST multipart
    path("negotiate/<int:message_id>/", views.negotiate, name="negotiate"),  # POST
    path("fraud/<int:product_id>/", views.fraud_refresh, name="fraud_refresh"),  # POST
]
