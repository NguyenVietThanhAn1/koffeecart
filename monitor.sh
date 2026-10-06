#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# KoffeeCart health report
#
#   ./monitor.sh          one-shot report; exit code 1 if something critical is wrong
#   ./monitor.sh logs     follow all logs
#   ./monitor.sh errors   error lines from the last 2 hours
#   ./monitor.sh stats    live CPU / memory per container
#
# Critical (exit 1): a container down or unhealthy, /health/ not ok, database unreachable.
# Warnings only: disk above 85%, newest backup older than 26 hours, errors in recent logs.
# ─────────────────────────────────────────────────────────
set -uo pipefail  # no -e: every check runs and reports, the exit code is decided at the end

cd "$(dirname "$0")" || exit 1
ENV_FILE=.env.prod
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
APP_URL=${APP_URL:-http://localhost}
CONTAINERS=(koffeecart_db koffeecart_web koffeecart_nginx)

[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }
env_value() {
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//" || true
}
DB_NAME=$(env_value DB_NAME)
DB_USER=$(env_value DB_USER)

if [ -t 1 ]; then
    RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' BLUE='\033[0;34m' NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' NC=''  # plain text in logs and CI
fi
FAILED=0
ok()   { echo -e "  ${GREEN}OK${NC}    $*"; }
warn() { echo -e "  ${YELLOW}WARN${NC}  $*"; }
fail() { echo -e "  ${RED}FAIL${NC}  $*"; FAILED=1; }
section() { echo -e "\n${BLUE}$*${NC}"; }

check_containers() {
    section "[1] Containers"
    local name status health
    for name in "${CONTAINERS[@]}"; do
        status=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo missing)
        health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || echo none)
        if [ "$status" != running ]; then
            fail "$name is $status"
        elif [ "$health" = healthy ] || [ "$health" = none ]; then
            ok "$name running ($health)"
        else
            fail "$name running but $health"
        fi
    done
}

check_http() {
    section "[2] Application"
    local body
    if body=$(curl -fsS --max-time 5 "$APP_URL/health/" 2>&1) && echo "$body" | grep -q '"status": "ok"'; then
        ok "$APP_URL/health/ -> $body"
    else
        fail "$APP_URL/health/ -> ${body:-no answer}"
    fi
}

check_database() {
    section "[3] Database"
    local tables
    tables=$("${COMPOSE[@]}" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At \
        -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null)
    if [[ "$tables" =~ ^[0-9]+$ ]] && [ "$tables" -gt 0 ]; then
        ok "PostgreSQL answers, $tables tables in $DB_NAME"
    else
        fail "cannot query $DB_NAME as $DB_USER"
    fi
}

check_disk() {
    section "[4] Disk"
    local used
    used=$(df -P . | awk 'NR == 2 { gsub("%", "", $5); print $5 }')
    if [ "${used:-0}" -ge 85 ]; then
        warn "disk ${used}% used (docker system prune / old backups?)"
    else
        ok "disk ${used}% used"
    fi
}

check_backups() {
    section "[5] Backups"
    local newest age_h
    newest=$(find backups -maxdepth 1 -name 'koffeecart_*.sql.gz' -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -n 1)
    if [ -z "$newest" ]; then
        warn "no backups yet (backups/backup.sh, or enable the systemd timer)"
        return
    fi
    age_h=$(( ($(date +%s) - ${newest%%.*}) / 3600 ))
    if [ "$age_h" -ge 26 ]; then
        warn "newest backup is ${age_h}h old: ${newest#* }"
    else
        ok "newest backup ${age_h}h old: ${newest#* }"
    fi
}

check_errors() {
    section "[6] Errors in web logs (last hour)"
    local count
    count=$("${COMPOSE[@]}" logs --since 1h web 2>/dev/null | grep -ciE 'error|exception|traceback')
    if [ "${count:-0}" -eq 0 ]; then
        ok "none"
    else
        warn "$count line(s); latest:"
        "${COMPOSE[@]}" logs --since 1h web 2>/dev/null | grep -iE 'error|exception|traceback' | tail -n 5 | sed 's/^/        /'
    fi
}

check_resources() {
    section "[7] Resources"
    docker stats --no-stream --format '  {{.Name}}  CPU {{.CPUPerc}}  MEM {{.MemUsage}}' "${CONTAINERS[@]}" 2>/dev/null \
        || warn "docker stats not available"
}

case "${1:-report}" in
    logs)   "${COMPOSE[@]}" logs -f ;;
    errors) "${COMPOSE[@]}" logs --since 2h 2>/dev/null | grep -iE 'error|exception|traceback|fatal' ;;
    stats)  docker stats "${CONTAINERS[@]}" ;;
    report)
        echo "KoffeeCart monitor - $(date '+%Y-%m-%d %H:%M:%S')"
        check_containers
        check_http
        check_database
        check_disk
        check_backups
        check_errors
        check_resources
        if [ "$FAILED" -eq 0 ]; then
            echo -e "\n${GREEN}All critical checks passed.${NC}"
        else
            echo -e "\n${RED}Critical problem found (see FAIL above).${NC}"
        fi
        exit "$FAILED"
        ;;
    *) echo "Unknown command: $1 (logs | errors | stats)" >&2; exit 1 ;;
esac
