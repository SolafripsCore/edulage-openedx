#!/usr/bin/env bash
# Nightly logical backup of the EduLage pilot: Open edX MySQL + MongoDB, Keycloak Postgres,
# Tutor config/plugins and Keycloak compose env. Complements DigitalOcean's weekly droplet images
# (whole-disk, point-in-time) with daily, restorable per-database dumps.
#
#   sudo install -m 0755 scripts/pilot/backup.sh /usr/local/sbin/edulage-backup
#   echo '17 2 * * * root /usr/local/sbin/edulage-backup >> /var/log/edulage-backup.log 2>&1' \
#     | sudo tee /etc/cron.d/edulage-backup
#
# Dumps land in $BACKUP_ROOT/<UTC timestamp>/ ; sets older than $KEEP_DAYS are pruned.
# Verify with scripts/pilot/restore_check.sh <set>.
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/var/backups/edulage}
KEEP_DAYS=${KEEP_DAYS:-14}
TUTOR_ROOT=${TUTOR_ROOT:-/home/tutor/.local/share/tutor}
KC_DIR=${KC_DIR:-/home/tutor/infra/keycloak}
MYSQL=${MYSQL_CONTAINER:-tutor_local-mysql-1}
MONGO=${MONGO_CONTAINER:-tutor_local-mongodb-1}
KCDB=${KCDB_CONTAINER:-edulage-keycloak-db}

stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest="$BACKUP_ROOT/$stamp"
mkdir -p "$dest"
chmod 700 "$BACKUP_ROOT" "$dest"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "MySQL (all application databases; MySQL system schemas excluded so the dump restores anywhere)"
docker exec "$MYSQL" sh -c 'dbs=$(mysql -N -uroot -p"$MYSQL_ROOT_PASSWORD" -e "show databases" 2>/dev/null \
  | grep -Ev "^(mysql|sys|information_schema|performance_schema)$"); \
  exec mysqldump --databases $dbs --single-transaction --quick --routines --triggers --events \
  -uroot -p"$MYSQL_ROOT_PASSWORD" 2>/dev/null' | gzip -1 > "$dest/mysql.sql.gz"

log "MongoDB (modulestore, forum)"
docker exec "$MONGO" sh -c 'exec mongodump --archive --gzip --quiet' > "$dest/mongo.archive.gz"

log "Keycloak Postgres"
docker exec "$KCDB" sh -c 'exec pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$dest/keycloak.pgdump"

log "Configuration"
tar -C / -czf "$dest/config.tar.gz" \
  --exclude="${TUTOR_ROOT#/}/env/build" \
  "${TUTOR_ROOT#/}/config.yml" "${TUTOR_ROOT#/}/env" \
  "${KC_DIR#/}" \
  "${PLUGINS_DIR:-home/tutor/.local/share/tutor-plugins}"
tar -tzf "$dest/config.tar.gz" | grep -c "tutor/config.yml$" >/dev/null

log "Uploaded media / course assets are in MySQL+Mongo (GridFS) for this deployment; nothing extra to copy"

( cd "$dest" && sha256sum -- * > SHA256SUMS )
chmod 600 "$dest"/*

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

log "done: $dest ($(du -sh "$dest" | cut -f1)); sets kept: $(ls -1 "$BACKUP_ROOT" | wc -l)"
