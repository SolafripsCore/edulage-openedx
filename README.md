# edulage-openedx

Deployment configuration for the EduLage learning engine — [Open edX](https://github.com/openedx/openedx-platform) run via [Tutor](https://docs.tutor.edly.io/).

Open edX itself is **not** vendored here; Tutor pulls the official images. This repo holds
everything EduLage-specific so the environment can be rebuilt from scratch:

- `config.public.yml` — non-secret Tutor settings (hosts, platform name, plugins).
- `scripts/bootstrap.sh` — provisions a fresh Ubuntu 24.04 host (Docker, firewall, swap, Tutor).
- `scripts/deploy.sh` — applies config and launches/updates the platform.
- `plugins/` — Tutor plugins for EduLage (branding, settings, tenant hosts, IdP proxy).
- `platform-plugin-edulage/` — Django plugin: EduLage OIDC backend, role-claim sync,
  admission-gated enrolment filter, admissions integration API.
- `infra/keycloak/` — stand-in EduLage identity provider used by the SSO spike.
- `scripts/spike/` — seed scripts and runtime test suites (tenant isolation, admissions, SSO).
- `scripts/pilot/` — controlled pilot content: `retire_demo_course.py` (removes the stock DemoX course), `seed_pilot_content.py` (CMS shell; one sample course per test institution, UNIA CS101 / UNIB MGT101), `seed_pilot_learners.py` (LMS shell; admitted enrolments + one demo certificate).
- `docs/spike-multitenancy-sso.md` — spike report: architecture, SSO, roles, isolation findings,
  data mapping, API/events, security, limitations, production plan, estimate.
- `theme/` — EduLage comprehensive theme / brand package. *(to come)*

Secrets (`*_PASSWORD`, `*_SECRET`, `*_KEY`) live only in the server's
`~/.local/share/tutor/config.yml` and in the team password manager — never commit them.

## Environments

| Env | LMS | Studio | MFEs | Host |
|---|---|---|---|---|
| pilot | https://learn.edulage.org | https://studio.edulage.org | https://apps.learn.edulage.org | DigitalOcean `edulage-openedx-pilot` (fra1, s-4vcpu-8gb) |

## Operating

```bash
ssh <admin-user>@<host>            # named admin from scripts/harden.sh; root SSH is disabled
sudo -iu tutor                       # Tutor is pip-installed in ~/venv (needed for Python plugins)
tutor local status                 # containers
tutor local logs -f lms            # logs
tutor local do createuser --staff --superuser <user> <email>
tutor local do importdemocourse    # demo course
tutor config save --set KEY=VALUE && tutor local launch -I   # apply config change
```

Upgrades: follow https://docs.tutor.edly.io/local.html#upgrading-from-older-releases — one named
release at a time, on staging first.

## Architecture

See `EduLage_OpenEdX_Approach.md` in the product docs: the Next.js marketplace (`SolafripsCore/EduLage`)
is the public face and control plane; Open edX is the replaceable learning engine behind it,
integrated via OIDC SSO, enrolment API, and openedx-events/filters.
