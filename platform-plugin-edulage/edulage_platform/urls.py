from django.urls import include, path, re_path

from .admissions import apply_view, decide_view, upload_view
from .console import console_view, invite_accept_view, invite_view, revoke_invitation_view, revoke_member_view
from .partners import admin_view, approve_view, decline_view
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
    re_path(rf"^apply/{COURSE_ID}/$", apply_view, name="apply"),
    path("institution/<str:org>/admissions/upload/", upload_view, name="console-admissions-upload"),
    path("institution/<str:org>/admissions/<int:pk>/<str:decision>/", decide_view, name="console-admissions-decide"),
    path("institution/", console_view, name="console"),
    path("institution/<str:org>/", console_view, name="console-org"),
    path("institution/<str:org>/invite/", invite_view, name="console-invite"),
    path("institution/<str:org>/invitations/<int:pk>/revoke/", revoke_invitation_view, name="console-revoke-invitation"),
    path("institution/<str:org>/members/<str:username>/revoke/", revoke_member_view, name="console-revoke-member"),
    path("invite/<str:token>/", invite_accept_view, name="invite"),
    path("admin/partners/", admin_view, name="partners"),
    path("admin/partners/<int:pk>/approve/", approve_view, name="partners-approve"),
    path("admin/partners/<int:pk>/decline/", decline_view, name="partners-decline"),
]
