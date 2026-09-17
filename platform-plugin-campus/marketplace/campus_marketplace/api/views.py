"""
Marketplace API (product layer): catalogue listings pushed from the marketplace control
plane, public run/institution/catalogue reads for the marketplace site, and the public partner
request form. Installed only with ``platform-plugin-campus[marketplace]``.

PUT  /campus/api/v1/listings/   {"listings": [{"course_id": "...", "institution": "ORG", "institution_name": "...",
  "classification": "degree", "credential": "MSc", "programme_title": "...", ...}]}
  Presentation metadata from the marketplace catalogue for course runs (upsert, idempotent).
GET  /campus/api/v1/runs/?course_id=...   (public)
  Enrolment policy (admission / open_free / open_paid) and price per run, for marketplace CTAs.
GET  /campus/api/v1/institutions/<code>/   (public)   institution profile + listed runs.
GET  /campus/api/v1/catalogue/              (public)   live institutions and open runs.
POST /campus/api/v1/partner-requests/       (public, throttled)   institution onboarding request.
"""
from django.conf import settings
from django.db import transaction
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from campus_platform.api.views import IntegrationView, _absolute_media_url
from campus_platform.provisioning import CODE_RE

from ..models import CourseListing


LISTING_FIELDS = (
    "institution", "institution_name", "institution_logo", "institution_url", "programme_title", "programme_url",
    "classification", "credential", "delivery_mode", "enrolment_policy", "price", "currency",
)
PUBLIC_RUN_FIELDS = ("course_id", "enrolment_policy", "price", "currency", "institution", "institution_name", "classification")


def _serialize_listing(course_key, listing, org=None):
    if listing is not None:
        data = listing.as_dict()
    else:
        data = {f: "" for f in LISTING_FIELDS}
        data.update(
            enrolment_policy=CourseListing.POLICY_ADMISSION,
            price="0.00",
            currency="NGN",
            institution=course_key.org,
            institution_name=(org.name if org else course_key.org),
            institution_logo=_absolute_media_url(org.logo.url) if org and org.logo else "",
            classification="",
            classification_label="Course",
        )
    data["course_id"] = str(course_key)
    return data


class ListingsView(IntegrationView):
    def put(self, request):
        items = request.data.get("listings")
        if not isinstance(items, list):
            return Response({"error": "listings must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        valid = {c for c, _ in CourseListing.CLASSIFICATIONS}
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                return Response({"error": "each listing must be an object"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                course_key = CourseKey.from_string(item["course_id"])
            except (KeyError, TypeError, InvalidKeyError):
                return Response({"error": "course_id is required and must be valid"}, status=status.HTTP_400_BAD_REQUEST)
            if item.get("classification", "short") not in valid:
                return Response({"error": f"unknown classification for {course_key}"}, status=status.HTTP_400_BAD_REQUEST)
            if item.get("enrolment_policy", CourseListing.POLICY_ADMISSION) not in {p for p, _ in CourseListing.POLICIES}:
                return Response({"error": f"unknown enrolment_policy for {course_key}"}, status=status.HTTP_400_BAD_REQUEST)
            defaults = {f: item[f] for f in LISTING_FIELDS if f in item}
            defaults.setdefault("institution", course_key.org)
            defaults.setdefault("institution_name", course_key.org)
            parsed.append((course_key, defaults))
        result = []
        with transaction.atomic():
            for course_key, defaults in parsed:
                listing, _ = CourseListing.objects.update_or_create(course_key=course_key, defaults=defaults)
                result.append(_serialize_listing(course_key, listing))
        return Response({"listings": result})


class PublicRunsView(APIView):
    """
    Public, unauthenticated: enrolment policy and price for course runs, read by the marketplace site
    programme pages to render "Enrol now" / "Enrol now — ₦X" / "Apply".
    GET /campus/api/v1/runs/?course_id=...&course_id=...   (max 50)
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        keys = []
        for raw in request.query_params.getlist("course_id")[:50]:
            try:
                keys.append(CourseKey.from_string(raw))
            except InvalidKeyError:
                continue
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=keys)}
        runs = []
        for k in keys:
            data = _serialize_listing(k, listings.get(k))
            runs.append({f: data[f] for f in PUBLIC_RUN_FIELDS})
        return Response({"runs": runs})


class PartnerRequestThrottle(AnonRateThrottle):
    rate = "5/hour"


class PartnerRequestView(APIView):
    """
    Public, unauthenticated: an institution's request to join the marketplace from the the marketplace site form.
    POST /campus/api/v1/partner-requests/  → 202 {"status": "received"|"already_pending"}
    Nothing is provisioned here; a marketplace administrator reviews at /campus/admin/partners/.
    """

    authentication_classes = ()
    permission_classes = ()
    throttle_classes = (PartnerRequestThrottle,)
    REQUIRED = ("institution_name", "contact_name", "contact_email")
    LIMITS = {"institution_name": 160, "short_name": 16, "country": 80, "website": 200, "contact_name": 120, "contact_email": 254, "contact_role": 120, "message": 4000}

    def post(self, request):
        from .. import partners  # pylint: disable=import-outside-toplevel

        data = request.data if isinstance(request.data, dict) else {}
        if data.get("company"):  # honeypot field, hidden on the form
            return Response({"status": "received"}, status=status.HTTP_202_ACCEPTED)
        clean = {k: str(data.get(k) or "").strip() for k in self.LIMITS}
        problems = [k for k in self.REQUIRED if not clean[k]] + [k for k, v in clean.items() if len(v) > self.LIMITS[k]]
        if "@" not in clean["contact_email"] or "." not in clean["contact_email"].rpartition("@")[2]:
            problems.append("contact_email")
        if clean["website"] and not clean["website"].startswith(("http://", "https://")):
            clean["website"] = "https://" + clean["website"]
        if clean["short_name"] and not CODE_RE.match(clean["short_name"].upper()):
            problems.append("short_name")
        if problems:
            return Response({"error": "invalid", "fields": sorted(set(problems))}, status=status.HTTP_400_BAD_REQUEST)
        req, created = partners.record_request(clean)
        return Response({"status": "received" if created else "already_pending", "id": req.pk}, status=status.HTTP_202_ACCEPTED)


class PublicInstitutionView(APIView):
    """
    Public, unauthenticated: an institution's profile and listed course runs, read by the marketplace site to
    render /institutions/<code> for institutions onboarded through the partner queue (no static entry).
    GET /campus/api/v1/institutions/<code>/  → 404 unless the code is an active organisation with a tenant.
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request, code):
        from eox_tenant.models import Route, TenantConfig  # pylint: disable=import-outside-toplevel
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel
        from organizations.models import Organization  # pylint: disable=import-outside-toplevel

        code = code.upper()
        org = Organization.objects.filter(short_name=code, active=True).first()
        tenant = TenantConfig.objects.filter(external_key=code.lower()).first()
        if not org or not tenant:
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
        route = Route.objects.filter(config=tenant).first()
        host = route.domain if route else settings.LMS_BASE
        overviews = CourseOverview.objects.filter(org=code).exclude(catalog_visibility="none").order_by("display_name")
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=[o.id for o in overviews])}
        courses = []
        for o in overviews:
            data = _serialize_listing(o.id, listings.get(o.id), org)
            courses.append({
                **{f: data[f] for f in PUBLIC_RUN_FIELDS},
                "title": o.display_name,
                "start": o.start.isoformat() if o.start else None,
                "end": o.end.isoformat() if o.end else None,
                "image": _absolute_media_url(o.course_image_url) if o.course_image_url else "",
                "about_url": f"https://{host}/courses/{o.id}/about",
            })
        return Response({
            "code": code,
            "name": _institution_name(org, tenant),
            "host": host,
            "website": tenant.meta.get("website", ""),
            "country": tenant.meta.get("country", ""),
            "logo": _absolute_media_url(org.logo.url) if org.logo else "",
            "courses": courses,
        })


def _institution_name(org, tenant):
    return (
        tenant.lms_configs.get("CAMPUS_INSTITUTION_NAME")
        or org.description
        or tenant.lms_configs.get("PLATFORM_NAME", "").split(" on ")[0]
        or org.name
    )


class PublicCatalogueView(APIView):
    """
    Public, unauthenticated: every live institution (active organisation with a tenant) and every
    course run open for self-enrolment, read by the the marketplace site homepage for real counts and an
    "Enrol now" strip. Admission-only runs are counted but not listed.
    GET /campus/api/v1/catalogue/
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        from eox_tenant.models import Route, TenantConfig  # pylint: disable=import-outside-toplevel
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel
        from organizations.models import Organization  # pylint: disable=import-outside-toplevel

        tenants = {t.external_key.upper(): t for t in TenantConfig.objects.exclude(external_key="")}
        orgs = [o for o in Organization.objects.filter(active=True) if o.short_name.upper() in tenants]
        hosts = {r.config_id: r.domain for r in Route.objects.filter(config__in=[tenants[o.short_name.upper()] for o in orgs])}
        institutions = []
        for o in orgs:
            t = tenants[o.short_name.upper()]
            institutions.append({
                "code": o.short_name.upper(),
                "name": _institution_name(o, t),
                "host": hosts.get(t.id, settings.LMS_BASE),
                "country": t.meta.get("country", ""),
                "logo": _absolute_media_url(o.logo.url) if o.logo else "",
            })
        by_code = {i["code"]: i for i in institutions}
        overviews = CourseOverview.objects.filter(org__in=list(by_code)).exclude(catalog_visibility="none")
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=[o.id for o in overviews])}
        open_courses = []
        for o in sorted(overviews, key=lambda c: c.start or c.created, reverse=True):
            listing = listings.get(o.id)
            if listing is None or not listing.is_open:
                continue
            inst = by_code[o.org.upper()]
            data = _serialize_listing(o.id, listing)
            open_courses.append({
                **{f: data[f] for f in PUBLIC_RUN_FIELDS},
                "title": o.display_name,
                "institution_name": inst["name"],
                "institution_logo": inst["logo"],
                "start": o.start.isoformat() if o.start else None,
                "image": _absolute_media_url(o.course_image_url) if o.course_image_url else "",
                "about_url": f"https://{inst['host']}/courses/{o.id}/about",
            })
        return Response({
            "counts": {
                "institutions": len(institutions),
                "courses": len(overviews),
                "open_courses": len(open_courses),
                "countries": len({i["country"] for i in institutions if i["country"]}),
            },
            "institutions": institutions,
            "open_courses": open_courses[:12],
        })
