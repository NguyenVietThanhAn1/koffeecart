#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# KoffeeCart database backup
#
# Usage:
#   backups/backup.sh                      back up now (verified), then delete old dumps
#   backups/backup.sh list                 list dumps
#   backups/backup.sh restore              pick a dump interactively and restore it
#   backups/backup.sh restore FILE --yes   restore FILE without questions (scripts, drills)
#   backups/backup.sh clean                delete dumps older than RETENTION_DAYS
#
# Reads DB_NAME / DB_USER from .env.prod. Optional settings (environment or .env.prod):
#   BACKUP_RETENTION_DAYS   default 7
#   BACKUP_OFFSITE          an rclone destination (e.g. "b2:koffeecart-backups"); when set,
#                           every verified dump is also copied off the server
# Scheduled by deploy/systemd/koffeecart-backup.timer (see docs/DEPLOY_LINUX.md).
# ─────────────────────────────────────────────────────────
# pipefail: in "pg_dump | gzip" a failing pg_dump must fail the whole pipeline.
# Without it only gzip's exit code counts, and gzip of nothing is a "successful" backup.
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$BACKUP_DIR")"
ENV_FILE="$PROJECT_DIR/.env.prod"
LOG_FILE="$PROJECT_DIR/logs/backup.log"
COMPOSE=(docker compose --project-directory "$PROJECT_DIR" --env-file "$ENV_FILE" -f "$PROJECT_DIR/docker-compose.prod.yml")

[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }

env_value() {
    # Value of KEY in .env.prod (last one wins), without sourcing the file as shell code.
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//" || true
}
DB_NAME=$(env_value DB_NAME)
DB_USER=$(env_value DB_USER)
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-$(env_value BACKUP_RETENTION_DAYS)}
RETENTION_DAYS=${RETENTION_DAYS:-7}
OFFSITE=${BACKUP_OFFSITE:-$(env_value BACKUP_OFFSITE)}
: "${DB_NAME:?DB_NAME missing in .env.prod}" "${DB_USER:?DB_USER missing in .env.prod}"

mkdir -p "$PROJECT_DIR/logs"
ERRORS=$(mktemp)  # pg_dump's stderr, so a failure is logged instead of thrown away
trap 'rm -f "$ERRORS"' EXIT

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

psql_db() {
    # psql inside the db container; extra arguments are passed through
    "${COMPOSE[@]}" exec -T db psql -v ON_ERROR_STOP=1 --username="$DB_USER" "$@"
}

require_db_running() {
    if [ -z "$("${COMPOSE[@]}" ps --status running -q db)" ]; then
        log "ERROR database container is not running"
        exit 1
    fi
}

verify_dump() {
    # A good dump is valid gzip and ends with pg_dump's completion marker.
    local file=$1
    gzip -t "$file" 2>/dev/null || return 1
    gzip -dc "$file" | tail -n 5 | grep -q 'PostgreSQL database dump complete'
}

do_backup() {
    require_db_running
    local file
    file="$BACKUP_DIR/koffeecart_$(date +%Y%m%d_%H%M%S).sql.gz"

    log "Backup started -> $(basename "$file")"
    if ! "${COMPOSE[@]}" exec -T db pg_dump --username="$DB_USER" --dbname="$DB_NAME" \
            --no-owner --format=plain 2>"$ERRORS" | gzip > "$file"; then
        log "BACKUP FAILED: pg_dump error: $(tr '\n' ' ' < "$ERRORS")"
        rm -f "$file"
        exit 1
    fi
    if ! verify_dump "$file"; then
        log "BACKUP FAILED: $(basename "$file") is incomplete or corrupt"
        rm -f "$file"
        exit 1
    fi
    log "BACKUP OK $(basename "$file") ($(du -h "$file" | cut -f1))"

    if [ -n "$OFFSITE" ]; then
        if command -v rclone > /dev/null; then
            if rclone copy "$file" "$OFFSITE"; then
                log "OFFSITE OK copied to $OFFSITE"
            else
                log "OFFSITE FAILED copy to $OFFSITE"
                exit 1
            fi
        else
            log "OFFSITE FAILED: BACKUP_OFFSITE is set but rclone is not installed"
            exit 1
        fi
    fi

    do_clean
}

do_clean() {
    local old
    old=$(find "$BACKUP_DIR" -maxdepth 1 -name 'koffeecart_*.sql.gz' -type f -mtime +"$RETENTION_DAYS")
    if [ -n "$old" ]; then
        echo "$old" | xargs rm -f
        log "CLEAN removed $(echo "$old" | wc -l) dump(s) older than $RETENTION_DAYS days"
    fi
}

list_dumps() {
    find "$BACKUP_DIR" -maxdepth 1 -name 'koffeecart_*.sql.gz' -type f | sort
}

do_list() {
    local dumps
    dumps=$(list_dumps)
    if [ -z "$dumps" ]; then
        echo "No backups found in $BACKUP_DIR"
        return
    fi
    echo "$dumps" | while read -r f; do
        printf '  [%s] %s  %s\n' "$(echo "$dumps" | grep -nxF "$f" | cut -d: -f1)" \
            "$(basename "$f")" "$(du -h "$f" | cut -f1)"
    done
}

do_restore() {
    local file=${1:-} confirm=${2:-}
    if [ -z "$file" ]; then
        do_list
        read -r -p "Number of the backup to restore (q to quit): " choice
        [ "$choice" = "q" ] && exit 0
        file=$(list_dumps | sed -n "${choice}p")
    fi
    [ -f "$file" ] || { echo "No such backup: $file" >&2; exit 1; }
    verify_dump "$file" || { log "RESTORE REFUSED: $(basename "$file") is incomplete or corrupt"; exit 1; }

    if [ "$confirm" != "--yes" ]; then
        echo "This will REPLACE database '$DB_NAME' with $(basename "$file")."
        read -r -p "Type yes to continue: " answer
        [ "$answer" = "yes" ] || { echo "Cancelled."; exit 0; }
    fi

    require_db_running
    log "RESTORE started from $(basename "$file")"
    # Stop the app so nothing writes while the database is replaced.
    "${COMPOSE[@]}" stop web
    # WITH (FORCE) (PostgreSQL 13+) closes any connection that is still open.
    psql_db --dbname=postgres \
        -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE);" \
        -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"
    gzip -dc "$file" | psql_db --quiet --dbname="$DB_NAME" > /dev/null
    "${COMPOSE[@]}" start web
    # Apply migrations newer than the dump (a no-op when the dump is current). exec uses the
    # image that is running now, whatever tag deploy.sh deployed.
    "${COMPOSE[@]}" exec -T web python manage.py migrate --noinput
    log "RESTORE OK from $(basename "$file")"
}

case "${1:-backup}" in
    backup)  do_backup ;;
    list)    do_list ;;
    clean)   do_clean ;;
    restore) do_restore "${2:-}" "${3:-}" ;;
    -h|--help) sed -n '2,18p' "$0" ;;
    *) echo "Unknown command: $1 (try --help)" >&2; exit 1 ;;
esac
