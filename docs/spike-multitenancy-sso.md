# Spike: multi-tenancy, SSO and admission-gated enrolment on Open edX

**Status:** complete — working proof of concept on the pilot server, all runtime suites green
(tenant isolation 24/24, admission 21/21, SSO/role sync for the 9 EduLage roles).
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
| Suspended/deactivated users | ✔ | `edulage_status=suspended` → `AuthForbidden` at login; API refuses (409) to admit `is_active=False` users |
| Start learning without another login | ✔ | admission suite: courseware 200 in the same SSO session |

Claims contract (what the production EduLage IdP must issue):

```json
{ "sub": "<edulage user id>", "email": "...", "name": "...",
  "edulage_status": "active" | "suspended" | "deactivated",
  "edulage_roles": ["learner", "institution_admin:UNIA", "instructor:course-v1:UNIB+MGT101+2026", ...] }
```

**Stand-in:** Keycloak 26 (`infra/keycloak/`) plays the EduLage IdP because the Next.js site has no
identity service yet. Nothing in Open edX depends on Keycloak — only on the OIDC discovery document
at `OIDC_ENDPOINT` and the two custom claims. Replacing it with Auth.js/Ory/Supabase Auth issuing
the same claims is a configuration change (`OAuth2ProviderConfig.other_settings.OIDC_ENDPOINT`).

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

Conclusion: **shared tenancy is viable for the pilot and first ~100 institutions with these
controls**; regulated/large institutions get a dedicated Tutor instance running the same plugin
(§8) — no contract changes.

## 4. Role and permission matrix

Claims are reconciled on every SSO login; roles previously granted by EduLage and no longer claimed
are revoked (`ManagedRole` table). Roles granted natively in Open edX are untouched.

| EduLage role | Claim | Open edX projection | Verified capability | Verified denial |
|---|---|---|---|---|
| Learner | `learner` | none (access via enrolment) | courseware after admission | direct enrol 403, instructor API, Studio |
| Institution administrator | `institution_admin:<ORG>` | `OrgStaffRole` + `OrgInstructorRole` + `OrgContentCreatorRole` | Studio (own org), instructor API, enrol self in own runs | any other org's Studio/instructor/exports |
| Programme administrator | `programme_admin:<ORG>` | `OrgStaffRole` | own org runs | other orgs — **programme scope not native** (§9) |
| Course author | `course_author:<ORG>` | `OrgContentCreatorRole` + Studio creator group | create/edit under own org | other orgs |
| Instructor | `instructor:<course run>` | `CourseInstructorRole` | Studio + instructor API for that run | other runs/orgs |
| Teaching assistant | `teaching_assistant:<course run>` | `CourseLimitedStaffRole` | instructor API (limited) | Studio authoring |
| Approved trainer | `trainer:<ORG>` | `OrgContentCreatorRole` | author under sponsoring org | other orgs |
| OEC support officer | `oec_support` | `SupportStaffRole` | `/support/` tools | instructor API, Studio |
| EduLage administrator | `edulage_admin` | `is_staff` (+ GlobalStaff) | all institutions, Studio, support, Django admin | — |

Revocation proof: `unib.instructor` claim replaced with `learner` → next login `roles: []`; claim
restored → `instructor` on `course-v1:UNIB+MGT101+2026` re-granted.

## 5. Admission-gated enrolment (Discover → Apply → Approve → Enrol → Learn)

`scripts/spike/admission_checks.py` (21/21) plays the EduLage control plane and a learner:

1. Discover/apply on `edulage.org` (out of scope for Open edX; EduLage records an application).
2. Learner (SSO session) tries `POST /api/enrollment/v1/enrollment` → **403**, not enrolled.
3. EduLage obtains a client-credentials JWT (`edulage-control-plane`) — issued on the platform host,
   **401 on a tenant host**.
4. `POST /edulage/api/v1/admissions/ {action: admit}` → `Admission(admitted)` + active enrolment.
5. Learner opens the courseware in the same SSO session → 200 ("Start learning", no second login).
6. Retry of step 4 → 200, no duplicate (idempotent).
7. `defer` → enrolment deactivated; learner cannot re-enrol directly (403); `admit` again restores.
8. `withdraw` → enrolment deactivated.
9. Guard rails: wrong institution for the run → 403; unknown learner → 404; malformed run → 400;
   anonymous → 401; deactivated user → 409.
10. Course team members (org/course roles) and platform staff bypass the gate (authoring/support).
11. `GET /edulage/api/v1/admissions/?username=&course_id=` for reconciliation.

## 6. Academic data mapping and ownership

| EduLage concept | Open edX record | Owner (source of truth) | Sync direction | Identifier |
|---|---|---|---|---|
| Institution | `Organization` + eox `TenantConfig`/`Route` | EduLage | EduLage → Open edX (on verification) | institution code = `org` |
| Programme | course family (`org+course` in key) | EduLage | none (Open edX has no programme object; listing lives on edulage.org) | `programme_id` ↔ `course` code |
| Intake / cohort | course run (`course-v1:ORG+CODE+RUN`) | EduLage (schedule) / Open edX (content) | EduLage creates run via Studio API or institution authors; EduLage stores the key | `course_key` |
| Applicant / learner | `auth.User` + `UserSocialAuth(edulage, sub)` | EduLage identity | JIT at SSO or via admissions API | `sub` (EduLage user id), email |
| Application | — | EduLage | not synced | `application_id` (stored on `Admission`) |
| Admission decision | `edulage_platform.Admission` | Institution (recorded by EduLage) | EduLage → Open edX | `(user, course_key)` unique |
| Enrolment | `CourseEnrollment` | Open edX (derived from Admission) | Open edX → EduLage event | `(user, course_key)` |
| Withdrawal / deferment | `Admission.status` + inactive `CourseEnrollment` | Institution via EduLage | EduLage → Open edX | as above |
| Progress / grades | `PersistentCourseGrade`, completion | Open edX | Open edX → EduLage events | `course_key`, `sub` |
| Completion → credential | `GeneratedCertificate` → EduLage credential record | Institution signs; EduLage issues | Open edX event → EduLage ledger | `certificate uuid` → `credential_id` |
| Results/transcripts | — | Institution | Open edX grades are *evidence*, not the record | — |

Rule: EduLage never reads Open edX tables; it uses the API above and the events below.

## 7. API and event specification

### 7.1 EduLage → Open edX (implemented)

```
Auth: OAuth2 client credentials → JWT
  POST https://learn.edulage.org/oauth2/access_token
       grant_type=client_credentials&client_id=edulage-control-plane&client_secret=…&token_type=jwt
  (refused on tenant hosts by eox-tenant; client user is is_staff, scopes: user_id)

POST /edulage/api/v1/admissions/                                 Authorization: JWT <token>
  {"username": "…" | "email": "…", "course_id": "course-v1:ORG+CODE+RUN",
   "application_id": "APP-1", "institution": "ORG", "action": "admit"|"withdraw"|"defer"}
  200 {"username", "course_id", "application_id", "institution", "status", "modified"}
      idempotent per (user, course run)
  400 malformed / missing / unknown action   403 institution ≠ course org   404 unknown user
  409 user account deactivated

GET  /edulage/api/v1/admissions/?username=…&course_id=…          reconciliation
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
6. **Status claim is only evaluated at login.** A user suspended in EduLage keeps an active LMS session
   until it expires (default 2 weeks). Production: shorten `SESSION_COOKIE_AGE` for staff, and have
   EduLage call `/api/user/v1/accounts/{u}/deactivate/` (or a plugin endpoint) on suspension.
7. **MFEs are org-unaware**; institution branding inside MFEs requires per-tenant `MFE_CONFIG`
   overrides (theme phase).
8. **Studio SSO relies on the LMS session** — fine, but Studio has no per-tenant host in this spike;
   institution scoping in Studio comes from roles, not from the host.

## 10. Security findings and production recommendations

Findings (spike):

- eox-tenant host binding of OAuth clients is a strong, free control — keep tenant hosts for
  institutions and reserve the platform host for the control plane and EduLage admins.
- The service client is `is_staff` + `IsAdminUser`: **over-privileged**. Production: dedicated
  permission class checking the JWT `client_id`/scope (`edulage:admissions`) instead of staff status,
  and per-institution service credentials if institutions ever call the API directly (they should
  not — only EduLage does).
- `ALLOW_PUBLIC_REGISTRATION` should be **false** in production; accounts originate from EduLage.
  Keep the local password login only for `edulage_admin` break-glass (or disable with
  `ENABLE_REQUIRE_THIRD_PARTY_AUTH`).
- Keycloak here uses dev-file storage and a bootstrap admin: **spike only**. Production IdP must be
  EduLage's own (Auth.js/Ory/managed Keycloak with Postgres), MFA for staff roles, short-lived tokens,
  key rotation via JWKS.
- Secrets: Tutor config, OIDC client secret, service client secret and Keycloak admin password live
  only on the server (`~/.local/share/tutor/config.yml`, `infra/keycloak/.env`); rotate the spike
  values before pilot.
- Admin surfaces (`/admin`, `/support/`, Studio maintenance) restricted to `edulage_admin`; add IP
  allow-listing or an identity-aware proxy for `/admin`.
- Add rate limiting on `/edulage/api/` and the OAuth token endpoint (Caddy or DRF throttles).
- Audit: every admissions API call and role grant/revoke is logged (`log.info` today) — ship to a
  central log store and expose to EduLage admins.

Recommended production design:

- **Identity:** EduLage IdP (OIDC) issuing `edulage_roles`/`edulage_status`; Open edX only trusts it.
- **Tenancy:** shared Tutor deployment + eox-tenant; one tenant host per institution; platform host
  for EduLage admins; dedicated instances as a premium/regulatory tier.
- **Authorisation:** roles pushed as claims (per-run for programme scope); admission filter on;
  self-registration off; service-scoped API permission.
- **Integration:** admissions API (implemented), webhooks with retries (§7.2), nightly reconciliation.
- **Hosting:** pilot on the current droplet; move MySQL/Redis to DO managed services and media to
  Spaces before onboarding paying institutions; k8s (DOKS) when >1 LMS replica is needed.
- **Observability:** Tutor logs → central store; uptime checks on all hosts; alert on webhook DLQ.

## 11. Implementation estimate (complete integration)

Estimated in Devin sessions (each roughly a focused working day); external waits noted separately.

| Work package | Sessions | Notes |
|---|---|---|
| EduLage identity service (OIDC issuer with roles/status claims, account linking UI, MFA for staff) | 3–4 | in `SolafripsCore/EduLage`; replaces Keycloak |
| Institution onboarding automation (org + tenant + branding + service creds from EduLage admin) | 1–2 | Django management command / API in plugin |
| Programme/intake → course run sync (create/link runs, validate keys, publish status) | 2 | Studio API + events |
| Admissions API hardening (service scopes, per-run role push, audit, throttles) | 1 | |
| Webhooks/events → EduLage (enrolment, progress, completion) + retries + DLQ | 2 | plugin + Next.js receivers |
| Credential ledger (completion → institution signing → verifiable credential) | 2–3 | EduLage side mostly |
| Learner "My Learning" on edulage.org (progress, continue learning, schedule) | 2 | consumes events/APIs |
| Reconciliation jobs + admin tooling | 1 | |
| Production hardening (managed DB/Redis, Spaces, secrets rotation, monitoring, backups drill) | 2 | DO provisioning waits |
| Theme phase (MFE brand package, per-tenant MFE config, authn page) | 3–4 | after this review |
| Dedicated-instance playbook + first migration rehearsal | 1–2 | only when a customer needs it |
| **Total** | **20–25 sessions** | plus institution content/pilot coordination |

## 12. Deployment and repository instructions

Server (`ssh root@165.22.82.204`, then `su - tutor`; Tutor lives in `~/venv`):

```bash
git clone https://github.com/SolafripsCore/edulage-openedx && cd edulage-openedx
scripts/deploy.sh                                   # config + plugins + plugin mount + build + launch
# Python-only plugin change:
rsync -a --exclude __pycache__ platform-plugin-edulage/ ~/platform-plugin-edulage/ && tutor local restart lms cms lms-worker cms-worker
# Migrations for the plugin:
tutor local run lms ./manage.py lms migrate edulage_platform

# Stand-in IdP (spike): infra/keycloak/.env with KEYCLOAK_ADMIN_PASSWORD, then
docker compose -f infra/keycloak/docker-compose.yml up -d
SPIKE_TEST_PASSWORD=… infra/keycloak/set-test-passwords.sh   # prints EDULAGE_OIDC_SECRET

# Seed institutions, OIDC provider, legacy account, service client:
tutor local run cms ./manage.py cms shell < scripts/spike/seed_cms.py
tutor local run -e EDULAGE_OIDC_SECRET=… -e EDULAGE_SERVICE_CLIENT_SECRET=… lms ./manage.py lms shell < scripts/spike/seed_lms.py

# Tests (from anywhere with internet):
SPIKE_TEST_PASSWORD=… python scripts/spike/tenant_checks.py                      # 24 checks
SPIKE_TEST_PASSWORD=… EDULAGE_SERVICE_CLIENT_SECRET=… python scripts/spike/admission_checks.py   # 21 checks
SPIKE_TEST_PASSWORD=… python scripts/spike/sso_login.py unia.admin                 # identity, roles, logout
scripts/spike/kc_set_roles.sh unib.instructor learner                            # revocation (on server)
```

Test identities (IdP realm `edulage`, password set by `set-test-passwords.sh`): `ada.learner`,
`sam.suspended`, `unia.admin`, `unia.programme`, `unia.author`, `unib.admin`, `unib.instructor`,
`unib.ta`, `unib.trainer`, `oec.support`, `edu.admin`. Courses: `course-v1:UNIA+CS101+2026`,
`course-v1:UNIB+MGT101+2026`. Tenant hosts: `unia.learn.edulage.org`, `unib.learn.edulage.org`.

## 13. Decisions for review

1. Adopt shared tenancy + eox-tenant for the pilot; dedicated instances as a paid/regulatory tier.
2. EduLage builds its own OIDC identity service (claims contract in §2.2) — replaces Keycloak.
3. Programme scope is implemented by EduLage pushing per-run claims, not by an Open edX construct.
4. Institutions never call Open edX directly; all writes go through EduLage's control plane.
5. Analytics for institutions come from EduLage (events → warehouse), not from shared Open edX
   dashboards.
6. Proceed to the theme phase on this architecture: tenant hosts carry institution branding; MFE
   header/account controls point at edulage.org.
