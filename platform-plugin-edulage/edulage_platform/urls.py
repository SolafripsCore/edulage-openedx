from django.urls import include, path, re_path

from .payments import callback_view, enrol_view, pay_view, webhook_view
from .status import register_view, status_view

COURSE_ID = r"(?P<course_id>course-v1:[^/+]+\+[^/+]+\+[^/]+)"

urlpatterns = [
    path("api/", include("edulage_platform.api.urls")),
    path("account/<slug:code>/", status_view, name="status"),
    path("register/", register_view, name="register"),
    path("pay/callback/", callback_view, name="pay-callback"),
    path("pay/webhook/", webhook_view, name="pay-webhook"),
    re_path(rf"^pay/{COURSE_ID}/$", pay_view, name="pay"),
    re_path(rf"^enrol/{COURSE_ID}/$", enrol_view, name="enrol"),
]
