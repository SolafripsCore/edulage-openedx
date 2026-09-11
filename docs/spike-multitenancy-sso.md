# Spike: multi-tenancy, SSO and admission-gated enrolment on Open edX

**Status:** complete — working proof of concept on the pilot server, all runtime suites green
(tenant isolation 24/24, admission 21/21, SSO/role sync for the 9 EduLage roles), followed by the
**controlled hardening** pass requested in the team review (§14: hardening items 1–10, compatibility
matrix, production acceptance requirements; `scripts/spike/hardening_checks.py`).
**Scope:** the brief in the colleague review (unified identity, institutional tenancy, academic
data mapping, admission-gated enrolment, role model, integration ownership, technical output).
**Verdict:** Open edX can serve as the EduLage learning engine behind `edulage.org` with a shared
multi-tenant deployment, **provided** the controls in §5 are in place. Organisation boundaries
alone are not sufficient isolation.

Everything here is reproducible: `scripts/spike/*.py` are the tests, `platform-plugin-edulage/`
is the code, `plugins/edulage.yml` + `config.public.yml` the configuration, `infra/keycloak/` the
stand-in identity provider.

---

## 1. Architecture

```
                 ┌──────────────────────────────────────────────────────────────┐
                 │ EduLage control plane (SolafripsCore/EduLage, Next.js/Vercel) │
   learner ────▶ │ edulage.org/programmes  (authoritative catalogue)             │
                 │ institutions · verification · programmes · intakes            │
                 │ applications · admissions · OECs · marketplace governance      │
                 │ identity provider (OIDC issuer)         [spike: Keycloak]      │
                 └───────┬──────────────────────────┬────────────────────────────┘
                         │ OIDC (browser)            │ integration API (JWT, server→server)
                         │ id_token: sub, email,     │ POST /edulage/api/v1/admissions/
                         │ edulage_roles[],          │ ◀── webhooks/events (§7)
                         │ edulage_status            │
                 ┌───────▼──────────────────────────▼────────────────────────────┐
                 │ Open edX (Tutor, DigitalOcean fra1)             learning engine │
                 │  ┌──────────────────────────────────────────────────────────┐  │
                 │  │ platform-plugin-edulage (Django plugin, openedx-filters) │  │
                 │  │  auth.EdulageOpenIdConnect   → SSO backend, status check │  │
                 │  │  pipeline.sync_edulage_roles → claims → CourseAccessRole │  │
                 │  │  filters.RequireAdmission    → blocks un-admitted enrol  │  │
                 │  │  api.AdmissionsView          → admit/withdraw/defer      │  │
                 │  └──────────────────────────────────────────────────────────┘  │
                 │  eox-tenant: host → TenantConfig (course_org_filter, branding)  │
                 │  learn.edulage.org        platform host (My Learning, admin)     │
                 │  unia.learn.edulage.org   tenant UNIA  ─┐ shared LMS/Studio/DB   │
                 │  unib.learn.edulage.org   tenant UNIB  ─┘                        │
                 │  studio.edulage.org       Studio (SSO via LMS OAuth2)            │
                 │  apps.learn.edulage.org   MFEs                                   │
                 └────────────────────────────────────────────────────────────────┘
                 Future: dedicated Tutor instance per regulated institution, same plugin/contracts.
```

Design rules confirmed by the spike:

- Open edX core is not forked. Everything EduLage-specific is a Tutor plugin (`plugins/edulage.yml`),
  a pip-installable Django plugin (`platform-plugin-edulage`, uses `openedx-filters`, social-auth
  pipeline, DRF) and data (tenants, organisations, provider config).
- `edulage.org` stays the catalogue; `learn.edulage.org` sends anonymous visitors there and shows
  logged-in learners "My Learning".
- Open edX is replaceable: EduLage only depends on OIDC, one REST endpoint it calls, and events it
  receives. None of the Open edX internals leak into the EduLage data model.

## 2. Unified identity and SSO

### 2.1 Sequence (login)

```
Learner          edulage.org (IdP)              learn.edulage.org (LMS)          studio.edulage.org
  │  click "Start learning" ─────────────────────────▶ /auth/login/edulage/?next=/courses/<run>
  │◀─────────────────── 302 to IdP /authorize (openid profile email) ──┤
  │  already signed in on edulage.org → no prompt (else login once)
  │──── code ───────────────────────────────────────▶ /auth/complete/edulage/
  │                                                    exchange code → id_token + userinfo
  │                                                    EdulageOpenIdConnect.get_user_details:
  │                                                      edulage_status != active → AuthForbidden
  │                                                    social pipeline:
  │                                                      match by email → link existing account
  │                                                      else JIT-create user (skip_registration_form)
  │                                                      sync_edulage_roles(claims) → CourseAccessRole
  │◀── session cookie, 302 next ────────────────────────┤
  │  open Studio ───────────────────────────────────────────────────────▶ /login/ → LMS OAuth2 authorize
  │                                                     already has LMS session → no prompt ──▶ Studio session
```

Logout: `TPA_AUTOMATIC_LOGOUT_ENABLED=True` + provider `logout_url` → LMS `/logout` clears the LMS
session and redirects to the IdP end-session endpoint (`post_logout_redirect_uri=https://edulage.org/`).
Studio sessions are OAuth2 children of the LMS session and expire with it.

### 2.2 What was proven (`scripts/spike/sso_login.py`, tenant/admission suites)

| Requirement | Result | Evidence |
|---|---|---|
| One EduLage account | ✔ | All test users exist only in the IdP; LMS accounts are created/linked at first SSO |
| SSO edulage.org → learn.edulage.org | ✔ | `sso_login.py <user>` → `/api/user/v1/me` 200 without LMS credentials |
| SSO → studio.edulage.org | ✔ | `studio_login()` reaches Studio home with no second prompt |
| Secure logout | ✔ | `/logout` → 302 to IdP end-session; `/api/user/v1/me` → 401 afterwards |
| Account linking (pre-existing LMS user) | ✔ | Legacy account seeded with same email; SSO attaches `UserSocialAuth`, no duplicate user |
| Role/permission claims | ✔ | `edulage_roles` claim → `CourseAccessRole` (§4); revocation re-tested (`kc_set_roles.sh`) |
| Suspended/deactivated users | ✔ | `edulage_status=suspended` → `AuthForbidden` at login; `POST /users/status/` suspends **immediately** (§14.4); API refuses (409) to admit `is_active=False` users |
| Account linking safety | ✔ | `email_verified` required, case-normalised match, ambiguity/already-linked refused and audited (§14.3) |
| Start learning without another login | ✔ | admission suite: courseware 200 in the same SSO session |

Claims contract (what the production EduLage IdP must issue):

```json
{ "sub": "<edulage user id — immutable, the cross-system principal>",
  "email": "...", "email_verified": true, "given_name": "...", "family_name": "...",
  "preferred_username": "...",
  "edulage_status": "active" | "suspended" | "deactivated",
  "edulage_roles": ["learner", "edulage_admin", "institution_admin:UNIA", "programme_admin:UNIA",
                    "course_author:UNIA", "trainer:UNIB", "oec_support:UNIA"] }
```

Claims are **compact** (global and institution-level only). Per-course-run entitlements
(`instructor:<run>`, `teaching_assistant:<run>`, `oec_support:<ORG>:<run>`) are *not* carried in
tokens; EduLage pushes them through the audited roles API (§7.1, §14.6).

**Identity provider decision (hardening item 1):** EduLage does *not* build its own OIDC issuer in
Next.js. Production identity is a mature OIDC provider — Keycloak (as run here, PostgreSQL-backed) or
an equivalent managed service — configured for MFA on staff/administrator roles, brute-force
protection, short access-token lifetime, refresh-token revocation and JWKS key rotation. Nothing in
Open edX depends on the vendor: only the discovery document at `OIDC_ENDPOINT`, the issuer/JWKS
validation and the claims contract above. `infra/keycloak/` is the reference deployment; the spike
realm and its test identities are fixtures, disabled with `scripts/spike/kc_disable_test_users.sh`
before any real user is onboarded.

## 3. Institutional tenancy

### 3.1 Model

| EduLage | Open edX | How |
|---|---|---|
| Institution | `organizations.Organization` (short_name = institution code, e.g. `UNIA`) | created by eox-tenant from `course_org_filter` |
| Institution domain | eox-tenant `Route` (`unia.learn.edulage.org`) → `TenantConfig` | `seed_lms.py`; Caddy patch in `plugins/edulage.yml` |
| Institution branding/name | `TenantConfig.lms_configs` (PLATFORM_NAME, logo, …) | per-tenant settings override |
| Institution course catalogue | `course_org_filter=[UNIA]` | eox-tenant filters course list, dashboard, search |

### 3.2 Findings (`scripts/spike/tenant_checks.py`, 24/24)

Positive:

- Anonymous course list on `unia.` shows only UNIA runs; on `unib.` only UNIB; the platform host hides
  tenant-claimed orgs.
- UNIA institution admin: Studio home lists only UNIA; can read own course settings and instructor API.
- UNIB instructor (course-scoped) sees only MGT101 in Studio.
- UNIB TA: instructor API on own course 200, **no** Studio authoring.
- OEC support: `/support/` 200, no instructor API.
- EduLage admin: Studio lists both institutions' courses; instructor API 200 on both; support tools.

Negative (all denied with 403/404):

- UNIA admin → UNIB Studio course settings, course team API, LMS instructor API, learner CSV export,
  enrolment list.
- UNIB instructor → UNIA Studio settings, UNIA instructor API.
- Learner → any instructor API, any Studio course.

### 3.3 Where organisation boundaries are NOT sufficient (and the added control)

| Gap in stock Open edX | Control added / required |
|---|---|
| A single LMS host shows every org's courses to everyone (catalogue, search, dashboard) | eox-tenant `course_org_filter` per host; platform host hides tenant orgs. **Institution UIs must live on tenant hosts**, never on `learn.` |
| Org-scoped staff (`OrgStaffRole`) get access to *every* course of that org, including future ones; there is no "programme" scope | Accepted for institution admin; programme admin gets `OrgStaffRole` today (over-broad, §9). Programme-level scoping needs a custom filter on the Studio/instructor endpoints or per-course roles pushed by EduLage |
| Self-enrolment is open to any logged-in user for any visible course | `RequireAdmission` filter on `CourseEnrollmentStarted` (403 without an `Admission`) |
| Any staff user with an OAuth token could call integration/enrolment APIs | Service client bound to platform host by eox-tenant (401 on tenant hosts); `IsAdminUser`; institution/org must match the course run |
| Django admin, `/api/user/v1/accounts`, analytics/Aspects, Insights, discussion search are **not** org-aware | Do not expose Django admin to institutions (EduLage admin only). Analytics must be served per-institution by EduLage (Aspects with org filters or EduLage's own warehouse), not shared dashboards |
| Studio course creation: `CourseCreator` + `org_course_creator_group` restrict *which* orgs, but a user with the global `course_creator_group` may create under any org | Only `edulage_admin` should hold the global group; institution roles get org-scoped rows only (pipeline does this) |
| Global settings (feature flags, email, theming) are per deployment | Per-tenant overrides via `TenantConfig`; anything contractual/regulatory → dedicated instance (§8) |
| Emails, certificates, notification templates default to platform branding | Per-tenant `lms_configs` overrides + Indigo theme variables; tested for platform name only |
| MFEs (learning, account, authn) are org-unaware and read config from `apps.learn.edulage.org` | eox-tenant can serve per-tenant MFE config via `MFE_CONFIG` overrides; not exercised here — theme phase |

Conclusion: **shared tenancy is pilot-validated with these controls** (two institutions, functional
isolation tests). No institution-count or concurrency figure is claimed until the load tests in
§14.11 have been run; regulated/large institutions get a dedicated Tutor instance running the same
plugin (§8) — no contract changes.

## 4. Role and permission matrix

Claims are reconciled on every SSO login; roles previously granted by EduLage from the *token* source
and no longer claimed are revoked. Per-run roles pushed through `PUT /edulage/api/v1/roles/` are
reconciled independently (`ManagedRole.source = api`): each source revokes only its own grants.
Roles granted natively in Open edX are untouched. `edulage_admin` is never granted by the API.

| EduLage role | Claim | Open edX projection | Verified capability | Verified denial |
|---|---|---|---|---|
| Learner | `learner` | none (access via enrolment) | courseware after admission | direct enrol 403, instructor API, Studio |
| Institution administrator | `institution_admin:<ORG>` | `OrgStaffRole` + `OrgInstructorRole` + `OrgContentCreatorRole` | Studio (own org), instructor API, enrol self in own runs | any other org's Studio/instructor/exports |
| Programme administrator | `programme_admin:<ORG>` | `OrgStaffRole` | own org runs | other orgs — **programme scope not native** (§9) |
| Course author | `course_author:<ORG>` | `OrgContentCreatorRole` + Studio creator group | create/edit under own org | other orgs |
| Instructor | `instructor:<course run>` (roles API) | `CourseInstructorRole` | Studio + instructor API for that run | other runs/orgs |
| Teaching assistant | `teaching_assistant:<course run>` (roles API) | `CourseLimitedStaffRole` | instructor API (limited) | Studio authoring |
| Approved trainer | `trainer:<ORG>` | `OrgContentCreatorRole` | author under sponsoring org | other orgs |
| OEC support officer | `oec_support:<ORG>[:<run>]` | `SupportScope` row (no Open edX role) | `GET /edulage/api/v1/support/learners/` — minimal summary of in-scope learners only | `/support/` tools, instructor API, Studio, grades, other institutions' learners |
| EduLage administrator | `edulage_admin` | `is_staff` (+ GlobalStaff) | all institutions, Studio, support, Django admin | — |

Revocation proof: `unib.instructor` claim replaced with `learner` → next login `roles: []`; claim
restored → `instructor` on `course-v1:UNIB+MGT101+2026` re-granted.

## 5. Admission-gated enrolment (Discover → Apply → Approve → Enrol → Learn)

`scripts/spike/admission_checks.py` (21/21) plays the EduLage control plane and a learner:

1. Discover/apply on `edulage.org` (out of scope for Open edX; EduLage records an application).
2. Learner (SSO session) tries `POST /api/enrollment/v1/enrollment` → **403**, not enrolled.
3. EduLage obtains a client-credentials JWT (`edulage-control-plane`) — issued on the platform host,
   **401 on a tenant host**.
4. `POST /edulage/api/v1/admissions/ {sub, action: admit}` → `Admission(admitted)` + active enrolment
   (200). If the applicant has never signed in, the admission is stored against the EduLage `sub`
   and the API returns **202 pending**; the first SSO attaches it and enrols automatically (§14.2).
5. Learner opens the courseware in the same SSO session → 200 ("Start learning", no second login).
6. Retry of step 4 → 200, no duplicate (idempotent).
7. `defer` → enrolment deactivated; learner cannot re-enrol directly (403); `admit` again restores.
8. `withdraw` → enrolment deactivated.
9. Guard rails: wrong institution for the run → 403; unknown learner → 404; malformed run → 400;
   anonymous → 401; deactivated user → 409.
10. Course team members (org/course roles) and platform staff bypass the gate (authoring/support).
11. `GET /edulage/api/v1/admissions/?sub=&course_id=` for reconciliation (`username=` remains for
    operator/migration tooling only).

## 6. Academic data mapping and ownership

| EduLage concept | Open edX record | Owner (source of truth) | Sync direction | Identifier |
|---|---|---|---|---|
| Institution | `Organization` + eox `TenantConfig`/`Route` | EduLage | EduLage → Open edX (on verification) | institution code = `org` |
| Programme | course family (`org+course` in key) | EduLage | none (Open edX has no programme object; listing lives on edulage.org) | `programme_id` ↔ `course` code |
| Intake / cohort | course run (`course-v1:ORG+CODE+RUN`) | EduLage (schedule) / Open edX (content) | EduLage creates run via Studio API or institution authors; EduLage stores the key | `course_key` |
| Applicant / learner | `auth.User` + `UserSocialAuth(edulage, sub)` | EduLage identity | pending admission by `sub`, account created/linked at first SSO | `sub` (immutable EduLage user id); email is descriptive only |
| Application | — | EduLage | not synced | `application_id` (stored on `Admission`) |
| Admission decision | `edulage_platform.Admission` | Institution (recorded by EduLage) | EduLage → Open edX | `(edulage_sub, course_key)` unique; `user` attached at first SSO |
| Enrolment | `CourseEnrollment` | Open edX (derived from Admission) | Open edX → EduLage event | `(user, course_key)` |
| Withdrawal / deferment | `Admission.status` + inactive `CourseEnrollment` | Institution via EduLage | EduLage → Open edX | as above |
| Progress / grades | `PersistentCourseGrade`, completion | Open edX | Open edX → EduLage events | `course_key`, `sub` |
| Completion → credential | `GeneratedCertificate` → EduLage credential record | **The institution awards and issues the qualification or credential. EduLage records, verifies and makes the credential independently verifiable.** | Open edX event → EduLage ledger | `certificate uuid` → `credential_id` |
| Results/transcripts | — | Institution | Open edX grades are *evidence*, not the record | — |

Rule: EduLage never reads Open edX tables; it uses the API above and the events below.

## 7. API and event specification

### 7.1 EduLage → Open edX (implemented)

```
Auth: OAuth2 client credentials → JWT
  POST https://learn.edulage.org/oauth2/access_token
       grant_type=client_credentials&client_id=edulage-control-plane&client_secret=…&token_type=jwt
  (refused on tenant hosts by eox-tenant; client user is is_staff, scopes: user_id)

  Caller must be the named service user in the `edulage_integration` Django group (staff status
  alone is not enough — hardening item 10/§14.10).

POST /edulage/api/v1/admissions/                                 Authorization: JWT <token>
  {"sub": "<edulage user id>", "course_id": "course-v1:ORG+CODE+RUN",
   "application_id": "APP-1", "institution": "ORG", "action": "admit"|"withdraw"|"defer"}
  200 {"sub", "username", "pending": false, "course_id", "application_id", "institution", "status", "modified"}
  202 same body, "pending": true, "username": null   — applicant has no LMS account yet; applied at first SSO
      idempotent per (sub, course run)
  400 malformed / missing / unknown action   403 institution ≠ course org
  409 user account suspended
  ("username"/"email" instead of "sub": migration/operator tooling only → 404 if unknown)

GET  /edulage/api/v1/admissions/?sub=…&course_id=…               reconciliation

PUT  /edulage/api/v1/roles/   {"sub", "roles": ["instructor:course-v1:…", "teaching_assistant:course-v1:…",
                                "oec_support:ORG[:course-v1:…]"]}
  200 — reconciles *API-sourced* grants to exactly this list (token-sourced grants untouched);
  400 if `edulage_admin` is requested; every grant/revoke → IdentityAudit
GET  /edulage/api/v1/roles/?sub=…

POST /edulage/api/v1/users/status/  {"sub", "active": false|true, "reason": "…"}
  200 — immediate suspension / reactivation (§14.4); enrolments preserved

GET  /edulage/api/v1/support/learners/?username=…                (OEC support officer's own SSO session)
  200 minimal summary (username, in-scope enrolments/admissions) for learners inside the caller's
      SupportScope; 403 outside scope or without any scope; audited as `support_lookup`
```

Stock Open edX APIs EduLage will also use (unchanged):
`/api/user/v1/accounts` (provision when learner has never signed in — or rely on JIT at SSO),
`/api/courses/v1/courses/?org=`, `/api/enrollment/v1/enrollment/{user},{run}`,
`/api/grades/v1/courses/{run}/`, `/api/certificates/v1/certificates/{user}/courses/{run}/`.

### 7.2 Open edX → EduLage (design; next phase)

Use **openedx-events** consumed in the plugin and forwarded as signed webhooks (HMAC-SHA256 over
body + timestamp, `X-EduLage-Signature`), delivered by a Celery task with exponential backoff and a
dead-letter table; each event carries an `event_id` (UUID) for consumer idempotency.

| Event | Source signal | EduLage action |
|---|---|---|
| `enrolment.changed` | `COURSE_ENROLLMENT_CREATED/CHANGED` | confirm admission → enrolment, detect drift |
| `progress.updated` | `PERSISTENT_GRADE_SUMMARY_CHANGED` | learner dashboard on edulage.org |
| `course.completed` | `CERTIFICATE_CREATED` / passing grade | create credential record, notify institution to sign |
| `course_run.published` | `COURSE_CATALOG_INFO_CHANGED` | attach run to intake, validate key/org |
| `user.login` | social-auth pipeline | audit, last-seen |

Also feasible via the Event Bus (Redis/Kafka) if EduLage grows a consumer; webhooks are simpler for
a Vercel-hosted control plane.

### 7.3 Errors, retries, idempotency

- EduLage calls are retried on 5xx/timeouts with backoff; `POST admissions` is idempotent so retries
  are safe. 4xx are terminal and surfaced to the admissions officer.
- The Admission table is the reconciliation anchor: a nightly job compares EduLage admissions with
  `GET admissions` and repairs drift (re-admit / withdraw).
- Webhooks: at-least-once delivery, consumer de-duplicates on `event_id`; failures land in a
  dead-letter table visible to EduLage admins.
- Token lifetime: client-credentials JWT ~1h; cache and refresh on 401.

## 8. Deployment evolution: shared → dedicated

The plugin and contracts are deployment-agnostic. A regulated institution moves to its own Tutor
instance (`inst.learn.edulage.org`, own DB/MongoDB/S3, in-country region if required) by:

1. Provision host, `scripts/bootstrap.sh`, `scripts/deploy.sh` with `LMS_HOST` for that institution.
2. Export/import course runs (`tutor local do exportcourse/importcourse` or OLX in Git).
3. Point EduLage's institution record at the new base URL and a new service client; same OIDC IdP.
4. Migrate enrolments/grades with Open edX's `CourseEnrollment`/grades APIs or DB copy during a
   maintenance window; identities carry over because `sub` is the EduLage id.

Cost/complexity note: each dedicated instance is ~$60–150/month infra plus upgrade toil, so this
tier should be priced accordingly.

## 9. Known Open edX limitations found

1. **No programme object / programme scope.** "Programme administrator" maps to org-wide staff.
   Real programme scoping requires EduLage to push per-run roles (`instructor:<run>` for each run in
   the programme) or a custom authorisation filter. Recommended: per-run claims generated by EduLage.
2. **Organisation ≠ tenant** for Django admin, user account API, global search, analytics — see §3.3.
3. **Org-scoped roles use `CourseKeyField.Empty`** sentinel semantics; any custom check must use it
   (bit us once: `course_id=""` raises `InvalidKeyError`).
4. **eox-tenant is a third-party plugin** (eduNEXT) tracking Open edX releases; pin versions and test
   on each upgrade. It changes OAuth token issuance (host-bound clients) — good for us, but must be
   documented for integrators.
5. **Third-party-auth config is a `ConfigurationModel`** (append-only rows, cached); automation must
   create new rows rather than update.
6. **Status claim is only evaluated at login** in stock Open edX, and its JWT-cookie authentication
   accepts inactive users, so `UserStandingMiddleware` alone does not stop an existing API session.
   Addressed by `POST /users/status/` + `AccountStatusMiddleware` (§14.4): suspension is immediate
   and staff sessions are clamped to 1 h.
7. **MFEs are org-unaware**; institution branding inside MFEs requires per-tenant `MFE_CONFIG`
   overrides (theme phase).
8. **Studio SSO relies on the LMS session** — fine, but Studio has no per-tenant host in this spike;
   institution scoping in Studio comes from roles, not from the host.

## 10. Security findings and production recommendations

Findings (spike):

- eox-tenant host binding of OAuth clients is a strong, free control — keep tenant hosts for
  institutions and reserve the platform host for the control plane and EduLage admins.
- The service client was `is_staff` + `IsAdminUser`: **over-privileged**. Now: the integration
  endpoints require membership of the `edulage_integration` group (a named service user; staff and
  even `edulage_admin` are refused — verified in `hardening_checks.py`). Institutions never call the
  API directly — only EduLage does.
- `ALLOW_PUBLIC_REGISTRATION` should be **false** in production; accounts originate from EduLage.
  Keep the local password login only for `edulage_admin` break-glass (or disable with
  `ENABLE_REQUIRE_THIRD_PARTY_AUTH`).
- Keycloak initially ran on dev-file (H2) storage; it now runs on PostgreSQL 16 (`infra/keycloak/`),
  with brute-force protection, 5-minute access tokens, refresh-token revocation and a TOTP policy in
  the realm. Conditional OTP is **enforced** for staff: members of `edulage-staff` carry the realm
  role `mfa-required`, and the bound browser flow `browser-staff-mfa` requires an OTP for that role
  (users without an authenticator are forced to enrol one at sign-in); learners are unaffected.
  Applied by `infra/keycloak/enforce-staff-mfa.py`, proven by `infra/keycloak/verify-staff-mfa.sh`
  (staff → `CONFIGURE_TOTP`, learner → straight back to the LMS). The master-realm admin has
  `CONFIGURE_TOTP` as a required action. Scripted SSO suites that need password-only staff logins
  must run against a copy of the realm or temporarily unbind the flow.
- Secrets: Tutor config, OIDC client secret, service client secret, Keycloak admin and DB passwords
  live only on the server (`~/.local/share/tutor/config.yml`, `infra/keycloak/.env`); the Keycloak
  values were rotated during the Postgres migration; the remaining spike values are rotated in the
  server-hardening step (§14.10) before any pilot user is onboarded.
- Admin surfaces (`/admin`, `/support/`, Studio maintenance) restricted to `edulage_admin`; add IP
  allow-listing or an identity-aware proxy for `/admin`.
- Add rate limiting on `/edulage/api/` and the OAuth token endpoint (Caddy or DRF throttles).
- Audit: every admissions API call and role grant/revoke is logged (`log.info` today) — ship to a
  central log store and expose to EduLage admins.

Recommended production design:

- **Identity:** a mature OIDC provider (PostgreSQL-backed Keycloak or equivalent) operated by EduLage,
  issuing compact `edulage_roles`/`edulage_status`; Open edX only trusts that issuer.
- **Tenancy:** shared Tutor deployment + eox-tenant; one tenant host per institution; platform host
  for EduLage admins; dedicated instances as a premium/regulatory tier.
- **Authorisation:** compact claims for global/institution roles; per-run roles and OEC scopes pushed
  through the audited roles API; admission filter on; self-registration off; integration endpoints
  restricted to the named service user.
- **Integration:** admissions API (implemented), webhooks with retries (§7.2), nightly reconciliation.
- **Hosting:** pilot on the current droplet; move MySQL/Redis to DO managed services and media to
  Spaces before onboarding paying institutions; k8s (DOKS) when >1 LMS replica is needed.
- **Observability:** Tutor logs → central store; uptime checks on all hosts; alert on webhook DLQ.

## 11. Implementation estimate (complete integration)

Estimated in Devin sessions (each roughly a focused working day); external waits noted separately.

| Work package | Sessions | Notes |
|---|---|---|
| Production identity provider (PostgreSQL Keycloak or managed OIDC: branded pages, MFA for staff, key rotation, EduLage user sync) | 2–3 | no bespoke issuer; EduLage's Next.js app becomes an OIDC client |
| Institution onboarding automation (org + tenant + branding + service creds from EduLage admin) | 1–2 | Django management command / API in plugin |
| Programme/intake → course run sync (create/link runs, validate keys, publish status) | 2 | Studio API + events |
| Admissions API hardening (service group, admission-by-sub, roles API, suspension, audit) | done | this PR; throttles/rate limits remain |
| Webhooks/events → EduLage (enrolment, progress, completion) + retries + DLQ | 2 | plugin + Next.js receivers |
| Credential ledger (completion → institution signing → verifiable credential) | 2–3 | EduLage side mostly |
| Learner "My Learning" on edulage.org (progress, continue learning, schedule) | 2 | consumes events/APIs |
| Reconciliation jobs + admin tooling | 1 | |
| Production hardening (managed DB/Redis, Spaces, secrets rotation, monitoring, backups drill) | 2 | DO provisioning waits |
| Theme phase (MFE brand package, per-tenant MFE config, authn page) | 3–4 | after this review |
| Dedicated-instance playbook + first migration rehearsal | 1–2 | only when a customer needs it |
| **Total** | **20–25 sessions** | plus institution content/pilot coordination |

## 12. Deployment and repository instructions

Server (`ssh <admin-user>@165.22.82.204` — named administrator created by `scripts/harden.sh`, root SSH disabled — then `sudo -iu tutor`; Tutor lives in `~/venv`):

```bash
git clone https://github.com/SolafripsCore/edulage-openedx && cd edulage-openedx
scripts/deploy.sh                                   # config + plugins + plugin mount + build + launch
# Python-only plugin change:
rsync -a --exclude __pycache__ platform-plugin-edulage/ ~/platform-plugin-edulage/ && tutor local restart lms cms lms-worker cms-worker
# Migrations for the plugin:
tutor local run lms ./manage.py lms migrate edulage_platform

# Identity provider (PostgreSQL-backed Keycloak): infra/keycloak/.env with
# KEYCLOAK_ADMIN_PASSWORD, KC_DB_PASSWORD (and optionally KC_DB_USERNAME), then
docker compose -f infra/keycloak/docker-compose.yml up -d
scripts/spike/kc_disable_test_users.sh            # disable spike identities ("enable" to re-enable for tests)
SPIKE_TEST_PASSWORD=… infra/keycloak/set-test-passwords.sh   # prints EDULAGE_OIDC_SECRET

# Seed institutions, OIDC provider, legacy account, service client:
tutor local run cms ./manage.py cms shell < scripts/spike/seed_cms.py
tutor local run -e EDULAGE_OIDC_SECRET=… -e EDULAGE_SERVICE_CLIENT_SECRET=… lms ./manage.py lms shell < scripts/spike/seed_lms.py

# Tests (from anywhere with internet):
SPIKE_TEST_PASSWORD=… python scripts/spike/tenant_checks.py                      # 24 checks
SPIKE_TEST_PASSWORD=… EDULAGE_SERVICE_CLIENT_SECRET=… python scripts/spike/admission_checks.py   # 21 checks
SPIKE_TEST_PASSWORD=… python scripts/spike/sso_login.py unia.admin                 # identity, roles, logout
SPIKE_SSH="ssh <admin-user>@…" SPIKE_TEST_PASSWORD=… EDULAGE_SERVICE_CLIENT_SECRET=… python scripts/spike/hardening_checks.py  # §14
scripts/spike/kc_set_roles.sh unib.instructor learner                            # revocation (on server)
```

Test identities (IdP realm `edulage`, password set by `set-test-passwords.sh`): `ada.learner`,
`sam.suspended`, `unia.admin`, `unia.programme`, `unia.author`, `unib.admin`, `unib.instructor`,
`unib.ta`, `unib.trainer`, `oec.support`, `edu.admin`, plus the hardening fixtures `bola.pending`,
`uv.learner`, `dupe.learner`. Courses: `course-v1:UNIA+CS101+2026`, `course-v1:UNIB+MGT101+2026`.
Tenant hosts: `unia.learn.edulage.org`, `unib.learn.edulage.org`. Operational runbooks (server
access, secret rotation, backup/restore, incident steps) live only in this private infrastructure
repository and are never copied into the public EduLage repository.

## 13. Decisions for review

1. Adopt shared tenancy + eox-tenant for the pilot (pilot-validated; scale claims after §14.11 load
   tests); dedicated instances as a paid/regulatory tier.
2. Production identity is a mature OIDC provider (PostgreSQL-backed Keycloak or managed equivalent)
   issuing the compact claims contract in §2.2 — EduLage does not build its own issuer.
3. Programme scope is implemented by EduLage pushing per-run roles through the audited roles API,
   not by token claims and not by an Open edX construct.
4. Institutions never call Open edX directly; all writes go through EduLage's control plane.
5. Analytics for institutions come from EduLage (events → warehouse), not from shared Open edX
   dashboards.
6. Proceed to the theme phase on this architecture: tenant hosts carry institution branding; MFE
   header/account controls point at edulage.org.

## 14. Controlled hardening (team review items 1–10) and production acceptance requirements

Each item below is implemented in this repository and exercised by `scripts/spike/hardening_checks.py`
on the pilot, unless marked *acceptance requirement* (must be true before the first real institution
is onboarded; verified operationally, not by code).

### 14.1 Identity provider
- **Decision:** mature OIDC provider (PostgreSQL-backed Keycloak, `infra/keycloak/`, or a managed
  equivalent); EduLage does not implement its own issuer. The Next.js app is an OIDC client of it.
- Realm policy: brute-force protection, 300 s access tokens, refresh-token revocation, 30 min SSO idle
  / 10 h max, external SSL required, TOTP policy defined.
- *Acceptance:* conditional OTP **enforced** for every `edulage_admin`, `institution_admin:*`,
  `programme_admin:*`, `oec_support:*` identity — done on the pilot realm (`edulage-staff` group →
  `mfa-required` role → `browser-staff-mfa` flow); signing-key rotation rehearsed (JWKS, Open edX keeps
  validating); realm admin console reachable only from the administration allow-list.

### 14.2 Admission before first login
- `Admission` is keyed by the immutable OIDC `sub` (`edulage_sub`, `user` nullable); unique per
  `(edulage_sub, course_key)`.
- `POST /admissions/ {sub}` → **200** when the learner already has an LMS account (enrolment synced),
  **202 pending** otherwise; the first SSO attaches the pending rows and enrols (`apply_pending_admissions`),
  audited as `admission_applied`. Idempotent; `withdraw`/`defer` deactivate the enrolment; the direct
  enrolment bypass remains blocked.

### 14.3 Account linking
- A pre-existing LMS account is linked only when the token carries `email_verified=true` **and**
  exactly one active LMS account matches the email case-insensitively **and** that account is not
  already bound to another EduLage `sub`. Otherwise the login is refused (`link_refused` audit row
  with the reason) — never silently merged. Manual recovery: EduLage admin links the
  `UserSocialAuth` in Django admin (`IdentityAudit` shows the refusal).

### 14.4 Immediate suspension
- `POST /users/status/ {sub, active:false}`: `is_active=False`, `UserStanding=disabled`, password
  rotated, OAuth access/refresh tokens deleted, all EduLage-managed roles and support scopes revoked,
  `suspended` audit row — in one transaction; a failure of any step fails the call so EduLage retries.
- `AccountStatusMiddleware` refuses *existing* sessions on the next request (Django session flushed,
  JWT cookies cleared → 403), without waiting for the next login; staff sessions are clamped to
  `EDULAGE_STAFF_SESSION_SECONDS` (3600) while learners keep the platform default.
- Enrolments are preserved; `active:true` restores the account and `sync_edulage_identity` re-applies
  roles at the next login.

### 14.5 OEC support scope
- `SupportStaffRole` is no longer granted. `oec_support:<ORG>[:<run>]` creates `SupportScope` rows;
  `GET /support/learners/` returns a minimal summary (username, in-scope enrolments/admissions) only
  for learners with an enrolment inside the officer's scope. No grades, discipline, finance, or
  other institutions' learners; each lookup is audited (`support_lookup`).

### 14.6 Compact claims and roles API
- Tokens carry global/institution roles only. `PUT /roles/` reconciles per-run roles from EduLage;
  API-sourced and token-sourced grants are tracked separately (`ManagedRole.source`) and each source
  revokes only its own grants. `edulage_admin` cannot be granted through the API.

### 14.7 Credential ownership
- The institution awards and issues the qualification or credential. EduLage records, verifies and
  makes the credential independently verifiable (§6). Open edX certificates are evidence, not the award.

### 14.8 Scale claims
- Shared tenancy is **pilot-validated** (two institutions, functional isolation). Capacity statements
  require the load tests in §14.11.

### 14.9 Compatibility matrix (pinned on the pilot; re-verify on every upgrade)

| Component | Version / source | Notes |
|---|---|---|
| Open edX named release | **Verawood** (`release/verawood.1`) | Tutor 22 series |
| edx-platform | `openedx/edx-platform` @ `9e67d14` (release/verawood.1) | inside `overhangio/openedx:22.0.2-indigo` |
| Tutor | 22.0.2 | `tutor-mfe` 22.0.0, `tutor-indigo` 22.0.0 |
| LMS/Studio image | `docker.io/overhangio/openedx:22.0.2-indigo` | Python 3.12.13, Django 5.2.13 |
| MFE image | `docker.io/overhangio/openedx-mfe:22.0.0-indigo` | built with Node 24.14.1; MFEs: account, admin-console, authn, authoring, communications, discussions, gradebook, learner-dashboard, learning, ora-grading, profile, site (catalog built but not the entry point) — all `release/verawood.1` |
| eox-tenant | 14.4.0 | `OPENEDX_EXTRA_PIP_REQUIREMENTS`; third-party (eduNEXT) |
| openedx-filters | 3.4.1 | `CourseEnrollmentStarted` filter |
| openedx-events | 11.2.0 | webhooks (§7.2, next phase) |
| social-auth-core | 4.9.0 | OIDC backend + pipeline hooks |
| edx-drf-extensions | 10.6.0 | JWT auth on the integration API |
| platform-plugin-edulage | 0.1.0 (this repo) | migrations `0001`, `0002_hardening` |
| Keycloak | 26.4 (`quay.io/keycloak/keycloak`) | PostgreSQL 16.6 |
| Infrastructure | MySQL 8.4.11, MongoDB 7.0.39, Redis 7.4.10, Meilisearch 1.36.0, Caddy 2.11.4, Docker 29.8.0, Ubuntu 24.04.4 LTS | DigitalOcean `s-4vcpu-8gb`, fra1, weekly backups |

### 14.10 Operational hardening (runbook in this private repository)
Applied on the pilot host (`scripts/harden.sh`, idempotent, one run per administrator):
- SSH key-only, root login disabled, password/keyboard-interactive auth off, `MaxAuthTries 3`;
  one named administrative user per operator (sudo + docker group; no shared accounts) — currently
  a single named operator account; Fail2ban `sshd` jail; UFW default-deny with 80/443 public.
- Secrets rotated (`scripts/rotate_secrets.sh`): OIDC client secret regenerated in Keycloak and
  written to a new `OAuth2ProviderConfig` row (never leaves the server); `edulage-control-plane`
  client secret replaced (old value verified rejected, 401). Keycloak admin/DB passwords were
  generated fresh at the Postgres migration.
- Spike identities disabled (`scripts/spike/kc_disable_test_users.sh`; SSO for `ada.learner` now
  refused). Re-enable with `... enable` only for a test window, disable again afterwards.

Still required before real users (*acceptance requirements*):
- SSH restricted to the administration allow-list (`ADMIN_CIDRS=` when re-running `harden.sh`) once
  the team's egress addresses are known; one named account per team administrator.
- Django admin, Keycloak admin console and `/support/` reachable only through the administration
  allow-list / identity-aware proxy (Caddy `remote_ip` matcher or a VPN).
- Rotate the remaining Tutor-generated credentials (MySQL/Mongo/Redis, `SECRET_KEY`, JWT keys) via
  `tutor config save` + relaunch during a maintenance window; the admissions/roles/status endpoints
  stay restricted to the named service user in `edulage_integration`.
- Backups: DigitalOcean weekly snapshots plus daily `tutor local do backup`-style dumps to Spaces;
  restore rehearsed once before pilot.

### 14.11 Load testing before any scale claim (*acceptance requirement*)
- Scripted mixed workload (SSO login, dashboard, courseware, assessments, admissions API) at target
  pilot concurrency; record p95 latency and error rate per tenant host; confirm no cross-tenant
  leakage under load; decide managed MySQL/Redis and DOKS thresholds from the results.

**Result (2026-09-09, pilot droplet: 4 vCPU / 8 GB, single host running LMS, CMS, workers, MySQL,
Mongo, Redis, Meilisearch, Keycloak).** Tool: k6 (`scripts/loadtest/`), journey = login → My learning
(dashboard API + learner-home init) → course outline → first unit (sequence metadata + xblock render) →
progress → logout, 2–7 s think time between pages, 20 throw-away learners on the UNIA run.

| Virtual users (continuously active) | p95 dashboard | p95 outline / unit | p95 login | host load (4 cores) | verdict |
|---|---|---|---|---|---|
| 30 | 0.5 s | 1.3 s / 1.1 s | 2.3 s | ~2.8, CPU ≈ 45 % idle | comfortable |
| 50 | 2.2 s | 3.0 s / 2.9 s | 4.4 s | ~5.1, CPU ≈ 0 % idle | degraded but functional |
| 60→100 ramp | 5.6 s | 6.0 s / 5.8 s | 10 s | 6.6, CPU saturated | not sustainable |

Findings:
- Tutor's default of **2 uWSGI workers** for the LMS was the first bottleneck (p50 7 s at only
  30 users with CPU 45 % idle). `OPENEDX_LMS_UWSGI_WORKERS=6` is now set on the pilot (throughput
  ×2, latencies at 30 users dropped ~10×). Beyond that the droplet is CPU-bound.
- No 5xx errors under load. The only request failures were Open edX's per-IP login rate limiter
  (`Too many failed login attempts`) tripping because all virtual users shared the k6 host IP — a
  test artefact (and a desirable control), not a capacity fault.
- Published figure: **the pilot host supports ~30 continuously active learners (≈300 signed-in
  learners at typical 10 % activity) at p95 < 2.5 s; ~50 with degraded response; not 100.** Beyond
  that, resize the droplet (8 vCPU) or split MySQL/Redis/Keycloak off the host (§8); the LMS is the
  scaling unit, since the rest of the stack stayed under 5 % CPU.
- Not measured: assessment submission, discussions, Studio authoring, per-tenant hosts under load.

### 14.12 Production acceptance checklist
1. Mature OIDC provider on persistent storage; MFA enforced for staff/admin roles; key rotation
   rehearsed (§14.1).
2. Admissions keyed by `sub`; 202-pending path verified end-to-end from edulage.org (§14.2).
3. Linking refusals visible to EduLage admins; recovery procedure documented (§14.3).
4. Suspension propagates within one request; reconciliation job for failed revocations (§14.4).
5. OEC support scoped; no `SupportStaffRole` grants exist (§14.5).
6. Roles API wired from EduLage; token claims remain compact (§14.6).
7. Credential wording in all user-facing text follows §14.7.
8. Capacity figure published from §14.11 results (~30 active / ~300 signed-in learners on the pilot
   host; re-test after any resize).
9. Compatibility matrix (§14.9) re-verified after each Tutor/Open edX upgrade.
10. Server hardening (§14.10): host baseline, secret rotation and identity disabling done; SSH/admin
    allow-list, remaining Tutor credential rotation and backup rehearsal outstanding.

### 14.13 Institution console (staff invitations)
Staff roles are granted, never self-declared. `/edulage/institution/<ORG>/` (LMS) is open to accounts
holding `institution_admin:<ORG>` (and to EduLage admins for every active institution); learners and
other staff get a branded 403. Administrators invite staff by e-mail with an institution-wide role
(`institution_admin`, `programme_admin`, `course_author`, `trainer`) or a course-run role
(`instructor`, `teaching_assistant`, restricted to the institution's own runs). The invitee follows a
signed link, signs in or registers with the invited address, and on acceptance the LMS (service
account `edulage-lms-console`, `manage-users` only) writes the claim into the account's
`edulage_roles` attribute on the IdP, adds it to `edulage-staff` (MFA) and mirrors the roles onto
Open edX through the existing `apply_roles` path; revocation reverses both. `edulage_roles` is a
managed, admin-only attribute in the realm user profile (`apply-realm-settings.py`); invitations
expire after 14 days and every step is recorded in `IdentityAudit`.
