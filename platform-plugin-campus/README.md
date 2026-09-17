# platform-plugin-campus

Brand-neutral Open edX plugin shared by EduLage and ITEMS eCampus. Two distributions:

| Package | Django app | Installed on | Contents |
|---|---|---|---|
| `platform-plugin-campus` | `campus_platform` | EduLage **and** ITEMS | eox-tenant tenancy, OIDC SSO + role sync, admission-gated enrolment, institution console, staff invitations, suspension, support scope, certificates, e-mails, institution provisioning, control-plane API, outbox events |
| `platform-plugin-campus-marketplace` (`marketplace/`) | `campus_marketplace` | EduLage only | course listings + public catalogue, open/free/paid self-enrolment, Paystack checkout + receipts, partner onboarding queue |

The marketplace layer is a separate package, not a flag: an ITEMS deployment that installs only
`platform-plugin-campus` has no marketplace models, tables, routes or settings.
`pip install platform-plugin-campus[marketplace]` pulls both.

## Layering

```
ITEMS control plane (Laravel)  ──OIDC / REST / webhooks──►  campus_platform  ──►  Open edX
EduLage control plane (Next.js) ──OIDC / REST / webhooks──►  campus_platform + campus_marketplace ──► Open edX
```

`campus_platform` never imports `campus_marketplace`. The product layer refines core behaviour
only through two settings-resolved hooks (`campus_platform/hooks.py`):

- `CAMPUS_ENROLMENT_POLICY_PROVIDER` — `callable(user, course_key) -> "admission" | "open" | "blocked:<msg>"`.
  Default: every course run requires an `Admission` from the control plane.
- `CAMPUS_COURSE_METADATA_PROVIDER` — `callable(course_key) -> dict` (programme title, credential,
  price…). Default: organisation name only.

`campus_marketplace/settings/common.py` points both at `campus_marketplace.policy`.

## Control-plane API (`/campus/api/v1/`)

Authenticated with an Open edX OAuth2/JWT client whose user is in `CAMPUS_INTEGRATION_GROUP`.

| Endpoint | Purpose |
|---|---|
| `POST /institutions/` · `DELETE /institutions/?code=` | provision / deactivate an institution (organisation + tenant config + host route, optional first admin invitation) |
| `POST /admissions/` | admit / withdraw / defer a learner for a course run |
| `PUT /roles/` | set a user's institution roles |
| `POST /users/status/` | suspend / reactivate |
| `PUT /support/learners/` | support-scope grants |
| `GET /events/?since=` · `POST /events/replay/` | reconciliation feed and audited replay of outbox events |
| `GET /tenant-hosts/check/`, `GET /me/`, `GET /dashboard/*`, `GET /credentials/<uuid>/` | host gating, learner dashboard, public credential verification |

Marketplace-only (`campus_marketplace`): `PUT /listings/`, `GET /runs/`, `GET /catalogue/`,
`GET /institutions/<code>/`, `POST /partner-requests/`.

## Events (Open edX → control plane)

`campus_platform/events.py`: transactional outbox (`OutboxEvent`) → Celery delivery to
`CAMPUS_WEBHOOK_URL`, HMAC-SHA256 signed (`X-Campus-Signature: v1=…` over `<timestamp>.<body>`),
UUID idempotency key, monotonic `sequence`, `version`, exponential retries (1 min → 8 h, 8 attempts),
dead-letter status, audited replay, pull-based reconciliation (`GET /events/`).

Types: `enrolment.created`, `enrolment.deactivated`, `course.completed`, `certificate.issued`,
`certificate.revoked`, `admission.applied`, `institution.provisioned`.

## Settings (all `CAMPUS_*`, defaults in `campus_platform/settings/common.py`)

Provisioning conventions:

```
CAMPUS_TENANT_HOST_TEMPLATE   "{code}.{lms_base}"          # EduLage: unia.learn.edulage.org
                              "{code}-ecampus.edusite.ng"  # ITEMS
CAMPUS_TENANT_PLATFORM_NAME   "{name} on {platform_name}"  # EduLage
                              "{name} eCampus"             # ITEMS
CAMPUS_TENANT_MKTG_ROOT       ""                           # optional "/" and "/courses" landing per tenant
```

Identity: `CAMPUS_KC_URL`, `CAMPUS_KC_REALM`, `CAMPUS_KC_CLIENT_ID`, `CAMPUS_KC_CLIENT_SECRET`
(institution console → IdP admin API). Webhooks: `CAMPUS_WEBHOOK_URL`, `CAMPUS_WEBHOOK_SECRET`.
Marketplace: `MARKETPLACE_PAYSTACK_SECRET_KEY`, `MARKETPLACE_PAYSTACK_PUBLIC_KEY`,
`MARKETPLACE_BILLING_EMAIL`, `MARKETPLACE_PARTNERS_EMAIL`.

## Tests

```
pip install "django<5.3" "edx-opaque-keys[django]<2.12" "openedx-events<10" celery requests
PYTHONPATH=.:marketplace DJANGO_SETTINGS_MODULE=tests.settings python -m django test tests
```

These cover the Open edX-independent parts (hooks, provisioning templates, outbox delivery,
signatures, marketplace policy). Filters, pipeline, console and API views need a Tutor dev
environment (`tutor dev`) with `eox-tenant`.

## Migrating EduLage from `platform-plugin-edulage`

The two packages ship fresh `0001_initial` migrations. The existing EduLage pilot database holds
`edulage_platform_*` tables; switching it requires a one-off data migration (rename tables and
`related_name`s, fake-apply `0001`, rename the social-auth provider `edulage` → `campus`,
`EDULAGE_*` → `CAMPUS_*`/`MARKETPLACE_*` settings). ITEMS starts on the new package directly.

## Licence

AGPL-3.0-only (imports edx-platform and eox-tenant). Proprietary control-plane logic belongs in
ITEMS / EduLage, not here.
