# EduLage pilot — operations runbook

Pilot host: DigitalOcean droplet `edulage-openedx-pilot` (fra1, s-4vcpu-8gb), Tutor in `/home/tutor`,
Keycloak in `/home/tutor/infra/keycloak`. Admin access: `ssh devin-ops@165.22.82.204` (key-only).

## Backups

Two independent layers:

| Layer | What | Schedule | Retention | Where |
|---|---|---|---|---|
| DigitalOcean droplet backups | whole-disk image | weekly (DO-managed) | 4 weeks | DO console → Droplet → Backups |
| `edulage-backup` (logical dumps) | MySQL (all Open edX DBs), MongoDB, Keycloak Postgres, Tutor `config.yml`/`env`/plugins, Keycloak compose dir | nightly 02:17 UTC (`/etc/cron.d/edulage-backup`) | 14 days | `/var/backups/edulage/<UTC stamp>/` (root-only) |

Each nightly set (~20 MB today) contains `mysql.sql.gz`, `mongo.archive.gz`, `keycloak.pgdump`,
`config.tar.gz` and `SHA256SUMS`. Log: `/var/log/edulage-backup.log`.
Source: `scripts/pilot/backup.sh` (installed as `/usr/local/sbin/edulage-backup`).

Run on demand: `sudo edulage-backup`.

Secrets caveat: `config.tar.gz` holds Tutor `config.yml` and the Keycloak `.env`, i.e. live credentials.
The directory is `0700 root`; copying sets off-host must go to encrypted storage only.

## Restore rehearsal

`scripts/pilot/restore_check.sh` (installed as `/usr/local/sbin/edulage-restore-check`) restores the
newest set into throw-away MySQL/Mongo/Postgres containers on an isolated network, compares row counts
for key tables with the live databases, and removes the containers. Production is never touched.

```
sudo edulage-restore-check            # newest set
sudo edulage-restore-check /var/backups/edulage/20260911T064615Z
```

Last rehearsal: 2026-09-11 — `RESTORE REHEARSAL PASSED` (18/18 counts matched: users, enrolments,
course overviews, organisations, tenants, admissions, payments, partner requests; modulestore + GridFS;
Keycloak users, credentials, role mappings, realms, clients). Repeat monthly or after schema changes.

## Real restore (disaster)

1. Rebuild the host from the latest DO droplet backup (fastest, includes everything), **or** on a fresh
   droplet: install Docker + Tutor, `tar -C / -xzf config.tar.gz`, `tutor local launch`.
2. Load dumps into the live containers:
   ```
   gunzip -c mysql.sql.gz | docker exec -i tutor_local-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
   docker exec -i tutor_local-mongodb-1 mongorestore --archive --gzip --drop < mongo.archive.gz
   docker exec -i edulage-keycloak-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < keycloak.pgdump
   ```
3. `tutor local restart`, `docker compose -f /home/tutor/infra/keycloak/docker-compose.yml restart`.
4. Verify: sign in at https://learn.edulage.org, open a course, check https://learn.edulage.org/edulage/admin/partners/.

## Monitoring and alerts

DigitalOcean Uptime checks (HTTPS, from eu_west/us_east/se_asia, every minute) for
`edulage.org`, `learn.edulage.org/heartbeat`, `studio.edulage.org/heartbeat`,
`apps.learn.edulage.org/learning/` and the `auth.edulage.org` OIDC discovery document.
Each has a *down* alert and an *SSL expiring in <14 days* alert e-mailed to the DigitalOcean account owner.
Manage: DO console → Monitoring → Uptime. Recreate/extend with `scripts/pilot/uptime_checks.py [emails…]`
(DigitalOcean only accepts e-mails of DO team members — invite them first under Settings → Team).

Droplet metrics/alerts (CPU, disk, memory) are available through the DO agent already installed; add
alert policies under Monitoring → Alerts when the pilot gets real traffic.

## Routine checks

- Weekly: `tail -3 /var/log/edulage-backup.log`, `df -h /` (backups use ~20 MB/night today).
- Monthly: `sudo edulage-restore-check`.
- After any Tutor/Keycloak config change: `sudo edulage-backup` (captures the new config).

## Institution hosts

Approving a partner request is the only step: `<code>.learn.edulage.org` serves within a minute.

- DNS: one wildcard record `*.learn` → droplet IP in Vercel DNS (`edulage.org`, team `solafrips-team1`);
  explicit `unia.learn` / `unib.learn` records are redundant but harmless.
- TLS: Caddy issues the certificate on the first visit (on-demand TLS). Before issuing it asks
  `GET lms:8000/edulage/api/v1/tenant-hosts/check/?domain=<host>`, which is 200 only when an eox-tenant
  `Route` for that host exists — so random names under `*.learn` are refused and cannot burn Let's Encrypt quota.
- Django: `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` accept `.learn.edulage.org` (`plugins/edulage.yml`,
  `EDULAGE_TENANT_DOMAIN`); no restart per institution.
- If the droplet IP changes, update `learn`, `*.learn`, `studio`, `auth`, `apps.learn`, `meilisearch.learn`.

## Known gaps

- Nightly sets stay on the same disk as production; off-host copy (DO Spaces, encrypted) is the next step.
