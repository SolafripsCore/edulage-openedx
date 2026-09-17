from django.urls import include, path, re_path

from .admissions import apply_view, decide_view, upload_view
from .console import console_view, invite_accept_view, invite_view, revoke_invitation_view, revoke_member_view
from .status import register_view, status_view

COURSE_ID = r"(?P<course_id>course-v1:[^/+]+\+[^/+]+\+[^/]+)"

urlpatterns = [
    path("api/", include("campus_platform.api.urls")),
    path("account/<slug:code>/", status_view, name="status"),
    path("register/", register_view, name="register"),
    re_path(rf"^apply/{COURSE_ID}/$", apply_view, name="apply"),
    path("institution/<str:org>/admissions/upload/", upload_view, name="console-admissions-upload"),
    path("institution/<str:org>/admissions/<int:pk>/<str:decision>/", decide_view, name="console-admissions-decide"),
    path("institution/", console_view, name="console"),
    path("institution/<str:org>/", console_view, name="console-org"),
    path("institution/<str:org>/invite/", invite_view, name="console-invite"),
    path("institution/<str:org>/invitations/<int:pk>/revoke/", revoke_invitation_view, name="console-revoke-invitation"),
    path("institution/<str:org>/members/<str:username>/revoke/", revoke_member_view, name="console-revoke-member"),
    path("invite/<str:token>/", invite_accept_view, name="invite"),
]
