#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Restore drill: prove that the newest backup can actually be restored.
#
#   backups/restore-drill.sh            use the newest dump in backups/
#   backups/restore-drill.sh FILE       use FILE
#
# The dump is restored into a throwaway database (<DB_NAME>_drill) in the running db
# container, a few key tables are counted, and the throwaway database is dropped again.
# The live database is never touched. Exit code 0 = the backup is usable.
# Scheduled weekly by deploy/systemd/koffeecart-restore-drill.timer.
# ─────────────────────────────────────────────────────────
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$BACKUP_DIR")"
ENV_FILE="$PROJECT_DIR/.env.prod"
LOG_FILE="$PROJECT_DIR/logs/backup.log"
COMPOSE=(docker compose --project-directory "$PROJECT_DIR" --env-file "$ENV_FILE" -f "$PROJECT_DIR/docker-compose.prod.yml")

env_value() {
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//" || true
}
DB_NAME=$(env_value DB_NAME)
DB_USER=$(env_value DB_USER)
: "${DB_NAME:?DB_NAME missing in .env.prod}" "${DB_USER:?DB_USER missing in .env.prod}"
DRILL_DB="${DB_NAME}_drill"

mkdir -p "$PROJECT_DIR/logs"
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}
psql_db() {
    "${COMPOSE[@]}" exec -T db psql -v ON_ERROR_STOP=1 --username="$DB_USER" "$@"
}

FILE=${1:-$(find "$BACKUP_DIR" -maxdepth 1 -name 'koffeecart_*.sql.gz' -type f | sort | tail -n 1)}
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    log "DRILL FAILED: no backup file found"
    exit 1
fi

cleanup() {
    psql_db --dbname=postgres -q -c "DROP DATABASE IF EXISTS \"$DRILL_DB\" WITH (FORCE);" > /dev/null 2>&1 || true
}
trap cleanup EXIT

started=$(date +%s)
log "DRILL started with $(basename "$FILE")"
cleanup
psql_db --dbname=postgres -q -c "CREATE DATABASE \"$DRILL_DB\" OWNER \"$DB_USER\";"
if ! gzip -dc "$FILE" | psql_db --quiet --dbname="$DRILL_DB" > /dev/null; then
    log "DRILL FAILED: $(basename "$FILE") does not restore cleanly"
    exit 1
fi

# The tables a working shop cannot do without. Accounts and products must not be empty.
counts=$(psql_db --dbname="$DRILL_DB" -At -F ' ' -c "
    SELECT 'accounts', count(*) FROM accounts_account
    UNION ALL SELECT 'products', count(*) FROM store_product
    UNION ALL SELECT 'orders', count(*) FROM orders_order
    UNION ALL SELECT 'migrations', count(*) FROM django_migrations;")
summary=$(echo "$counts" | tr '\n' ' ')
for table in accounts products migrations; do
    if ! echo "$counts" | grep -Eq "^$table [1-9][0-9]*$"; then
        log "DRILL FAILED: table '$table' is empty or missing after restore ($summary)"
        exit 1
    fi
done

log "DRILL OK $(basename "$FILE") restored in $(( $(date +%s) - started ))s: $summary"
