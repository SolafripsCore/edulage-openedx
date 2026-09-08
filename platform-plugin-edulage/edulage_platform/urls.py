from django.urls import include, path

from .status import status_view

urlpatterns = [
    path("api/", include("edulage_platform.api.urls")),
    path("account/<slug:code>/", status_view, name="status"),
]
