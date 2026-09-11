#!/usr/bin/env bash
# Set one password on every spike test user in the `edulage` realm and print the
# `openedx` client secret (needed by scripts/spike/seed_lms.py as EDULAGE_OIDC_SECRET).
#
#   SPIKE_TEST_PASSWORD=... ./set-test-passwords.sh
#
# Requires .env (KEYCLOAK_ADMIN_PASSWORD) next to this script; nothing is written to disk.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${SPIKE_TEST_PASSWORD:?export SPIKE_TEST_PASSWORD}"

kc() { docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
docker exec -e KP="$KEYCLOAK_ADMIN_PASSWORD" edulage-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password "$KP"' >/dev/null

for u in $(python3 -c 'import json;print(" ".join(x["username"] for x in json.load(open("realm-edulage.json"))["users"]))'); do
  kc set-password -r edulage --username "$u" --new-password "$SPIKE_TEST_PASSWORD"
  echo "password set: $u"
done

cid=$(kc get clients -r edulage -q clientId=openedx --fields id --format csv --noquotes)
echo "EDULAGE_OIDC_SECRET=$(kc get "clients/$cid/client-secret" -r edulage --fields value --format csv --noquotes)"
