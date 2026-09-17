from django.urls import include, path, re_path

from campus_platform.urls import COURSE_ID

from .partners import admin_view, approve_view, decline_view
from .payments import callback_view, enrol_view, pay_view, webhook_view

urlpatterns = [
    path("api/", include("campus_marketplace.api.urls")),
    path("pay/callback/", callback_view, name="pay-callback"),
    path("pay/webhook/", webhook_view, name="pay-webhook"),
    re_path(rf"^pay/{COURSE_ID}/$", pay_view, name="pay"),
    re_path(rf"^enrol/{COURSE_ID}/$", enrol_view, name="enrol"),
    path("admin/partners/", admin_view, name="partners"),
    path("admin/partners/<int:pk>/approve/", approve_view, name="partners-approve"),
    path("admin/partners/<int:pk>/decline/", decline_view, name="partners-decline"),
]
