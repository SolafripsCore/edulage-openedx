#!/usr/bin/env bash
# Rotate the two integration secrets shared between the IdP, Open edX and the EduLage control plane:
#   - the OIDC client secret of the `openedx` client in the `edulage` realm (regenerated in Keycloak,
#     written to a new OAuth2ProviderConfig row via scripts/spike/seed_lms.py)
#   - the client-credentials secret of `edulage-control-plane` (random, updated via seed_lms.py)
# Run on the server as the `tutor` user from a checkout of this repo (Tutor in ~/venv). Prints the
# new service secret ONCE for the operator to place in the control plane's secret store; the OIDC
# secret never leaves the server.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . infra/keycloak/.env; set +a

kc() { docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
docker exec -e KP="$KEYCLOAK_ADMIN_PASSWORD" edulage-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password "$KP"' >/dev/null
cid=$(kc get clients -r edulage -q clientId=openedx --fields id --format csv --noquotes)
kc create "clients/$cid/client-secret" -r edulage >/dev/null
oidc_secret=$(kc get "clients/$cid/client-secret" -r edulage --fields value --format csv --noquotes)
service_secret=$(python3 -c 'import secrets;print(secrets.token_urlsafe(40))')

tutor local run -e EDULAGE_OIDC_SECRET="$oidc_secret" -e EDULAGE_SERVICE_CLIENT_SECRET="$service_secret" \
  lms ./manage.py lms shell < scripts/spike/seed_lms.py | grep -E "^(provider|service)" || true
# Open edX caches third-party-auth ConfigurationModel rows; restart so the new row is read.
tutor local restart lms cms >/dev/null
echo "rotated OIDC client secret (server-only) and service client secret."
echo "EDULAGE_SERVICE_CLIENT_SECRET=$service_secret"
