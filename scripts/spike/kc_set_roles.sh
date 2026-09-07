#!/usr/bin/env bash
# Change a spike user's EduLage role claims in the stand-in IdP (run on the server).
#
#   ./kc_set_roles.sh <username> <role>[,<role>...]     e.g. ./kc_set_roles.sh unib.instructor learner
#
# Requires infra/keycloak/.env (KEYCLOAK_ADMIN_PASSWORD). Used to prove that role revocation in
# EduLage is reconciled onto Open edX at the user's next SSO login.
set -euo pipefail
cd "$(dirname "$0")/../../infra/keycloak"
set -a; . ./.env; set +a
user="$1"; roles="$2"

kc() { docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
docker exec -e KP="$KEYCLOAK_ADMIN_PASSWORD" edulage-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password "$KP"' >/dev/null

uid=$(kc get users -r edulage -q "username=$user" -q exact=true --fields id --format csv --noquotes)
json=$(python3 -c 'import json,sys;print(json.dumps({"attributes":{"edulage_roles":sys.argv[1].split(","),"edulage_status":["active"]}}))' "$roles")
kc update "users/$uid" -r edulage -b "$json"
echo "$user edulage_roles=$roles"
