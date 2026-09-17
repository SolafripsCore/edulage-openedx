"""
Admissions wiring — the learner side (``/campus/apply/<course_id>/``) and the institution side
(admissions panel in the institution console, plus CSV decision upload).

A learner applies from the programme page on the product site; this records an ``Admission`` in
``submitted`` state, visible at once in My learning. The institution decides in its console
(admit / decline / defer, one at a time or by uploading a CSV of decisions); admitting enrols
the learner immediately (``identity.sync_enrolment``) and e-mails them. Decisions are only
ever taken by administrators of the institution that owns the course run.
"""
import csv
import io
import logging
import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from . import emails, events, hooks, identity
from .models import Admission

log = logging.getLogger(__name__)

DECISIONS = {
    "admit": Admission.STATUS_ADMITTED,
    "decline": Admission.STATUS_DECLINED,
    "defer": Admission.STATUS_DEFERRED,
    "review": Admission.STATUS_UNDER_REVIEW,
}
DECISION_MESSAGES = {
    Admission.STATUS_ADMITTED: (
        "You have been admitted",
        "Congratulations — {institution} has admitted you to {course}. The programme is now active on your "
        "My learning dashboard and you can start right away.",
        "Go to My learning",
    ),
    Admission.STATUS_DECLINED: (
        "Admission decision",
        "{institution} has reviewed your application to {course} and is unable to offer you a place on this "
        "occasion. Admission decisions rest solely with the institution; you may contact them directly for feedback.",
        "View your applications",
    ),
    Admission.STATUS_DEFERRED: (
        "Application deferred",
        "{institution} has deferred your application to {course}. You will be notified when the decision is "
        "reconsidered for a later intake.",
        "View your applications",
    ),
    Admission.STATUS_UNDER_REVIEW: (
        "Application under review",
        "{institution} is now reviewing your application to {course}. We will e-mail you as soon as a decision "
        "is recorded.",
        "View your applications",
    ),
}
MAX_CSV_ROWS = 2000


def _course_key(course_id):
    try:
        return CourseKey.from_string(course_id)
    except InvalidKeyError as exc:
        raise Http404 from exc


def _course_title(course_key):
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    overview = CourseOverview.objects.filter(id=course_key).first()
    return overview.display_name if overview else str(course_key)


def _institution_name(org):
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    o = Organization.objects.filter(short_name=org).first()
    return (o.description or o.name) if o else org


def _dashboard():
    return emails.lms_url("/dashboard")


def new_application_id():
    return f"APP-{secrets.token_hex(5).upper()}"


# ------------------------------------------------------------------------------------ learner


@never_cache
@login_required
def apply_view(request, course_id):
    """Record an application for an admission-required run and send the learner to My learning."""
    course_key = _course_key(course_id)
    from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

    if hooks.enrolment_policy(request.user, course_key) == hooks.POLICY_OPEN:
        CourseEnrollment.enroll(request.user, course_key, check_access=True)
        return HttpResponseRedirect(_dashboard())

    if CourseEnrollment.is_enrolled(request.user, course_key):
        return HttpResponseRedirect(_dashboard())
    if not request.user.is_active:
        return HttpResponseRedirect(_dashboard())

    with transaction.atomic():
        adm = Admission.objects.filter(user=request.user, course_key=course_key).first()
        if adm is None:
            adm = Admission.objects.create(
                user=request.user,
                identity_sub=identity.sub_for_user(request.user),
                course_key=course_key,
                application_id=new_application_id(),
                institution=course_key.org,
                status=Admission.STATUS_SUBMITTED,
            )
            created = True
        else:
            created = False
            if adm.status in (Admission.STATUS_WITHDRAWN, Admission.STATUS_DECLINED):
                adm.status = Admission.STATUS_SUBMITTED
                adm.application_id = new_application_id()
                adm.save(update_fields=["status", "application_id", "modified"])
                created = True
        if created:
            events.emit(
                "admission.applied",
                {"application_id": adm.application_id, "username": request.user.username, "status": adm.status},
                course_key=course_key, sub=adm.identity_sub or "",
            )
    if created:
        identity.audit("application_submitted", user=request.user, detail=f"{course_key} {adm.application_id}", actor="learner")
        course = _course_title(course_key)
        institution = _institution_name(course_key.org)
        emails.send_notice(
            [request.user.email],
            f"Application received — {course}",
            "Application received",
            f"Your application to {course} has been received",
            [
                f"{institution} will review your application and record its decision. "
                "You can follow the status on your My learning dashboard, and we will e-mail you when a decision is taken.",
            ],
            details=[("Application reference", adm.application_id), ("Institution", institution), ("Programme", course)],
            action_url=_dashboard(),
            action_label="View your applications",
        )
        log.info("campus: application %s %s → %s", adm.application_id, request.user.username, course_key)
    return HttpResponseRedirect(f"{_dashboard()}?applied={course_key}")


# --------------------------------------------------------------------------------- institution


def applications(org):
    """All applications for an institution's runs, open ones first, newest first within a group."""
    order = {s: i for i, s in enumerate((*Admission.OPEN_STATUSES, Admission.STATUS_DEFERRED))}
    rows = list(Admission.objects.filter(institution=org, user__isnull=False).select_related("user", "user__profile"))
    titles = {}
    for a in rows:
        titles.setdefault(a.course_key, None)
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    for o in CourseOverview.objects.filter(id__in=list(titles)):
        titles[o.id] = o.display_name
    items = []
    for a in rows:
        items.append({
            "pk": a.pk,
            "name": (a.user.profile.name if hasattr(a.user, "profile") else "") or a.user.username,
            "email": a.user.email,
            "course_id": str(a.course_key),
            "course": titles.get(a.course_key) or str(a.course_key),
            "application_id": a.application_id,
            "status": a.status,
            "status_label": a.get_status_display(),
            "open": a.status in Admission.OPEN_STATUSES or a.status == Admission.STATUS_DEFERRED,
            "modified": a.modified,
        })
    return sorted(items, key=lambda i: (order.get(i["status"], 9), -i["modified"].timestamp()))


def decide(adm, decision, actor):
    """Apply one decision to an admission (owned by the caller's institution — checked by the view)."""
    new_status = DECISIONS[decision]
    if adm.status == new_status:
        return False
    with transaction.atomic():
        adm.status = new_status
        adm.save(update_fields=["status", "modified"])
        identity.sync_enrolment(adm)
    identity.audit("admission_decided", user=adm.user, detail=f"{adm.course_key} {adm.status}", actor=actor.username)
    heading, body, label = DECISION_MESSAGES[new_status]
    course = _course_title(adm.course_key)
    institution = _institution_name(adm.institution)
    emails.send_notice(
        [adm.user.email],
        f"{heading} — {course}",
        "Admissions",
        heading,
        [body.format(institution=institution, course=course)],
        details=[("Application reference", adm.application_id), ("Institution", institution), ("Programme", course)],
        action_url=_dashboard(),
        action_label=label,
    )
    return True


def _guarded(request, org):
    from .console import _guard  # pylint: disable=import-outside-toplevel

    return _guard(request, org)


@never_cache
@require_POST
def decide_view(request, org, pk, decision):
    refused = _guarded(request, org)
    if refused:
        return refused
    if decision not in DECISIONS:
        raise Http404
    adm = get_object_or_404(Admission, pk=pk, institution=org, user__isnull=False)
    if adm.course_key.org != org:
        raise Http404
    if decide(adm, decision, request.user):
        messages.success(request, f"{adm.user.email}: {adm.get_status_display()} — {adm.course_key}.")
    else:
        messages.info(request, f"{adm.user.email} was already {adm.get_status_display().lower()}.")
    return redirect("campus:console-org", org=org)


@never_cache
@require_POST
def upload_view(request, org):
    """
    CSV of decisions: columns ``email``, ``course_id``, ``decision`` (admit/decline/defer/review).
    Rows for learners without an application are created as direct admissions (only for ``admit``),
    so an institution can admit applicants who applied through its own portal.
    """
    refused = _guarded(request, org)
    if refused:
        return refused
    upload = request.FILES.get("file")
    if upload is None or upload.size > 2_000_000:
        messages.error(request, "Choose a CSV file (up to 2 MB).")
        return redirect("campus:console-org", org=org)
    try:
        reader = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")))
        rows = list(reader)[: MAX_CSV_ROWS + 1]
    except (UnicodeDecodeError, csv.Error):
        messages.error(request, "The file is not a readable UTF-8 CSV.")
        return redirect("campus:console-org", org=org)
    if len(rows) > MAX_CSV_ROWS:
        messages.error(request, f"At most {MAX_CSV_ROWS} rows per upload.")
        return redirect("campus:console-org", org=org)
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    if not {"email", "course_id", "decision"} <= fields:
        messages.error(request, "The CSV needs the columns: email, course_id, decision.")
        return redirect("campus:console-org", org=org)

    User = get_user_model()
    applied, skipped = 0, []
    for n, raw in enumerate(rows, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        decision = row.get("decision", "").lower()
        try:
            course_key = CourseKey.from_string(row.get("course_id", ""))
        except InvalidKeyError:
            skipped.append(f"row {n}: invalid course_id")
            continue
        if course_key.org != org:
            skipped.append(f"row {n}: {course_key} is not one of your runs")
            continue
        if decision not in DECISIONS:
            skipped.append(f"row {n}: decision must be one of {', '.join(DECISIONS)}")
            continue
        users = list(User.objects.filter(email__iexact=row.get("email", ""), is_active=True)[:2])
        if len(users) != 1:
            skipped.append(f"row {n}: {'no active learner account' if not users else 'ambiguous e-mail'} ({row.get('email')})")
            continue
        user = users[0]
        adm = Admission.objects.filter(user=user, course_key=course_key).first()
        if adm is None:
            if decision != "admit":
                skipped.append(f"row {n}: {user.email} has not applied to {course_key}")
                continue
            adm = Admission.objects.create(
                user=user,
                identity_sub=identity.sub_for_user(user),
                course_key=course_key,
                application_id=new_application_id(),
                institution=org,
                status=Admission.STATUS_SUBMITTED,
            )
        if decide(adm, decision, request.user):
            applied += 1
    messages.success(request, f"{applied} decision{'s' if applied != 1 else ''} recorded from {upload.name}.")
    for s in skipped[:20]:
        messages.warning(request, s)
    if len(skipped) > 20:
        messages.warning(request, f"…and {len(skipped) - 20} more rows skipped.")
    return redirect("campus:console-org", org=org)
