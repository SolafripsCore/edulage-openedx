#!/usr/bin/env bash
# Restore rehearsal: load a backup set produced by backup.sh into throw-away containers on an
# isolated Docker network and compare key row counts with the live databases. Touches nothing
# in production. Exits non-zero on any mismatch.
#
#   sudo scripts/pilot/restore_check.sh [/var/backups/edulage/<set>]   (default: newest set)
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/var/backups/edulage}
set_dir=${1:-$(ls -1d "$BACKUP_ROOT"/*/ | sort | tail -1)}
set_dir=${set_dir%/}
MYSQL=${MYSQL_CONTAINER:-tutor_local-mysql-1}
MONGO=${MONGO_CONTAINER:-tutor_local-mongodb-1}
KCDB=${KCDB_CONTAINER:-edulage-keycloak-db}
tag=rr$$
net=edulage-restore-$tag
fail=0

log() { echo "[$(date -u +%FT%TZ)] $*"; }
cleanup() { docker rm -f "mysql-$tag" "mongo-$tag" "pg-$tag" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; }
trap cleanup EXIT

compare() { # label live restored
  if [ "$2" = "$3" ]; then log "OK   $1: $2"; else log "FAIL $1: live=$2 restored=$3"; fail=1; fi
}

log "set: $set_dir"
( cd "$set_dir" && sha256sum -c --quiet SHA256SUMS ) && log "checksums OK"

docker network create --internal "$net" >/dev/null
mysql_img=$(docker inspect -f '{{.Config.Image}}' "$MYSQL")
mongo_img=$(docker inspect -f '{{.Config.Image}}' "$MONGO")
pg_img=$(docker inspect -f '{{.Config.Image}}' "$KCDB")

log "starting scratch containers ($mysql_img, $mongo_img, $pg_img)"
docker run -d --rm --name "mysql-$tag" --network "$net" -e MYSQL_ROOT_PASSWORD=scratch "$mysql_img" >/dev/null
docker run -d --rm --name "mongo-$tag" --network "$net" "$mongo_img" >/dev/null
docker run -d --rm --name "pg-$tag" --network "$net" -e POSTGRES_PASSWORD=scratch "$pg_img" >/dev/null

for i in $(seq 1 60); do docker exec "mysql-$tag" mysql -uroot -pscratch -e 'select 1' >/dev/null 2>&1 && break; sleep 2; done
for i in $(seq 1 30); do docker exec "pg-$tag" psql -U postgres -c 'select 1' >/dev/null 2>&1 && break; sleep 2; done
for i in $(seq 1 30); do docker exec "mongo-$tag" mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 2; done

log "restoring MySQL"
gunzip -c "$set_dir/mysql.sql.gz" | docker exec -i "mysql-$tag" mysql -uroot -pscratch 2>&1 | grep -v 'insecure' || true
log "restoring MongoDB"
docker exec -i "mongo-$tag" mongorestore --archive --gzip --quiet --drop < "$set_dir/mongo.archive.gz"
log "restoring Keycloak Postgres"
docker exec "pg-$tag" createdb -U postgres keycloak
docker exec -i "pg-$tag" pg_restore -U postgres -d keycloak --no-owner --no-privileges < "$set_dir/keycloak.pgdump"

mysql_live() { docker exec "$MYSQL" sh -c "exec mysql -N -uroot -p\"\$MYSQL_ROOT_PASSWORD\" openedx -e \"$1\"" 2>/dev/null; }
mysql_rest() { docker exec "mysql-$tag" mysql -N -uroot -pscratch openedx -e "$1" 2>/dev/null; }
for t in auth_user student_courseenrollment course_overviews_courseoverview organizations_organization \
         eox_tenant_tenantconfig edulage_platform_admission edulage_platform_payment edulage_platform_partnerrequest; do
  compare "mysql $t" "$(mysql_live "select count(*) from $t")" "$(mysql_rest "select count(*) from $t")"
done

mongo_count() { docker exec "$1" mongosh --quiet openedx --eval "db.getCollection('$2').countDocuments()"; }
for c in modulestore.active_versions modulestore.structures modulestore.definitions fs.files; do
  compare "mongo $c" "$(mongo_count "$MONGO" "$c")" "$(mongo_count "mongo-$tag" "$c")"
done

pg_live() { docker exec "$KCDB" sh -c "exec psql -tA -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\" -c \"$1\""; }
pg_rest() { docker exec "pg-$tag" psql -tA -U postgres keycloak -c "$1"; }
for t in user_entity credential user_role_mapping realm client; do
  compare "keycloak $t" "$(pg_live "select count(*) from $t")" "$(pg_rest "select count(*) from $t")"
done

[ "$(tar -tzf "$set_dir/config.tar.gz" | grep -c 'tutor/config.yml$')" -gt 0 ] && log "OK   config archive contains tutor config.yml" || { log "FAIL config archive missing config.yml"; fail=1; }

[ $fail -eq 0 ] && log "RESTORE REHEARSAL PASSED" || { log "RESTORE REHEARSAL FAILED"; exit 1; }
