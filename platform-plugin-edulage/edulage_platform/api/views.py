"""
Integration API called by the EduLage control plane after an institution decides on an
application. Authenticated with an Open edX OAuth2/JWT token for a staff service user.

POST /edulage/api/v1/admissions/
  {"username": "..." | "email": "...", "course_id": "course-v1:ORG+CODE+RUN",
   "application_id": "APP-1", "institution": "ORG", "action": "admit" | "withdraw" | "defer"}
GET  /edulage/api/v1/admissions/?username=...&course_id=...

POST is idempotent per (user, course run): repeating a call converges on the same admission
status and enrolment state, so EduLage may retry on timeouts without side effects.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Admission

User = get_user_model()

ACTION_TO_STATUS = {
    "admit": Admission.STATUS_ADMITTED,
    "withdraw": Admission.STATUS_WITHDRAWN,
    "defer": Admission.STATUS_DEFERRED,
}


def _serialize(adm):
    return {
        "username": adm.user.username,
        "course_id": str(adm.course_key),
        "application_id": adm.application_id,
        "institution": adm.institution,
        "status": adm.status,
        "modified": adm.modified.isoformat(),
    }


class AdmissionsView(APIView):
    authentication_classes = (JwtAuthentication, SessionAuthenticationAllowInactiveUser)
    permission_classes = (IsAdminUser,)

    def get(self, request):
        qs = Admission.objects.select_related("user")
        if username := request.query_params.get("username"):
            qs = qs.filter(user__username=username)
        if course_id := request.query_params.get("course_id"):
            qs = qs.filter(course_key=CourseKey.from_string(course_id))
        return Response([_serialize(a) for a in qs[:500]])

    def post(self, request):
        from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

        data = request.data
        action = data.get("action", "admit")
        if action not in ACTION_TO_STATUS:
            return Response({"error": f"unknown action {action!r}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            course_key = CourseKey.from_string(data["course_id"])
            if "username" in data:
                user = User.objects.get(username=data["username"])
            else:
                user = User.objects.get(email__iexact=data["email"])
        except (KeyError, InvalidKeyError):
            return Response(
                {"error": "username (or email) and a valid course_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except User.DoesNotExist:
            return Response({"error": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        institution = data.get("institution", course_key.org)
        if institution != course_key.org:
            # The course run belongs to another institution's Open edX organisation.
            return Response(
                {"error": f"course {course_key} is not owned by institution {institution!r}"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.is_active and action == "admit":
            return Response({"error": "user account is deactivated"}, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            adm, _ = Admission.objects.update_or_create(
                user=user,
                course_key=course_key,
                defaults={
                    "application_id": data.get("application_id", ""),
                    "institution": institution,
                    "status": ACTION_TO_STATUS[action],
                },
            )
            if adm.is_active:
                CourseEnrollment.enroll(user, course_key, mode=data.get("mode", "honor"), check_access=False)
            elif CourseEnrollment.is_enrolled(user, course_key):
                CourseEnrollment.unenroll(user, course_key)

        return Response(_serialize(adm), status=status.HTTP_200_OK)
