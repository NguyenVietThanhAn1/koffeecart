#!/bin/bash
# ─────────────────────────────────────────────────────────
# Koffeecart System Monitor
# Usage: ./monitor.sh
#        ./monitor.sh logs     (xem live logs)
#        ./monitor.sh errors   (chỉ xem errors)
#        ./monitor.sh stats    (resource usage)
# ─────────────────────────────────────────────────────────

COMPOSE_FILE="docker-compose.prod.yml"
APP_URL="http://localhost"
LOG_DIR="./logs"

# ── Colors ───────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── Functions ─────────────────────────────────────────────
print_header() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Koffeecart Monitor — $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BLUE}══════════════════════════════════════════${NC}"
}

check_containers() {
    echo -e "\n${YELLOW}[1] Container Status${NC}"
    echo "──────────────────────────────────────────"

    services=("koffeecart_db" "koffeecart_web" "koffeecart_nginx")
    all_ok=true

    for service in "${services[@]}"; do
        status=$(docker inspect --format='{{.State.Status}}' "$service" 2>/dev/null)
        health=$(docker inspect --format='{{.State.Health.Status}}' "$service" 2>/dev/null)

        if [ "$status" = "running" ]; then
            if [ "$health" = "healthy" ] || [ "$health" = "" ]; then
                echo -e "  ${GREEN}✅ $service${NC} → running"
            else
                echo -e "  ${YELLOW}⚠️  $service${NC} → running (health: $health)"
            fi
        else
            echo -e "  ${RED}❌ $service${NC} → $status"
            all_ok=false
        fi
    done

    $all_ok && echo -e "\n  ${GREEN}All containers healthy!${NC}"
}

check_http() {
    echo -e "\n${YELLOW}[2] HTTP Health Check${NC}"
    echo "──────────────────────────────────────────"

    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$APP_URL")

    if [ "$response" = "200" ] || [ "$response" = "301" ] || [ "$response" = "302" ]; then
        echo -e "  ${GREEN}✅ $APP_URL → HTTP $response${NC}"
    else
        echo -e "  ${RED}❌ $APP_URL → HTTP $response (ALERT!)${NC}"
    fi
}

check_database() {
    echo -e "\n${YELLOW}[3] Database Check${NC}"
    echo "──────────────────────────────────────────"

    table_count=$(docker compose -f $COMPOSE_FILE exec -T db \
        psql -U koffeecart_user -d koffeecart_db \
        -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" \
        2>/dev/null | tr -d ' ')

    if [ -n "$table_count" ] && [ "$table_count" -gt 0 ]; then
        echo -e "  ${GREEN}✅ PostgreSQL connected — $table_count tables found${NC}"
    else
        echo -e "  ${RED}❌ Cannot connect to database!${NC}"
    fi
}

check_resources() {
    echo -e "\n${YELLOW}[4] Resource Usage${NC}"
    echo "──────────────────────────────────────────"
    docker stats --no-stream \
        koffeecart_db koffeecart_web koffeecart_nginx \
        --format "  {{.Name}}\t CPU: {{.CPUPerc}}\t MEM: {{.MemUsage}}"
}

check_disk() {
    echo -e "\n${YELLOW}[5] Disk Usage${NC}"
    echo "──────────────────────────────────────────"

    # Docker volumes
    echo "  Docker volumes:"
    docker system df 2>/dev/null | grep -E "TYPE|Images|Containers|Volumes" | \
        awk '{printf "  %-20s %-10s %-10s\n", $1, $3, $4}'

    # Log files
    echo ""
    echo "  Log files:"
    if [ -d "$LOG_DIR" ]; then
        du -sh $LOG_DIR/* 2>/dev/null | awk '{printf "  %-10s %s\n", $1, $2}'
    else
        echo "  (no log files yet)"
    fi
}

check_errors() {
    echo -e "\n${YELLOW}[6] Recent Errors (last 1 hour)${NC}"
    echo "──────────────────────────────────────────"

    error_count=$(docker compose -f $COMPOSE_FILE logs \
        --since 1h web 2>/dev/null | grep -ci "error\|exception\|traceback")

    if [ "$error_count" -eq 0 ]; then
        echo -e "  ${GREEN}✅ No errors in the last hour${NC}"
    else
        echo -e "  ${RED}⚠️  $error_count error(s) found in last hour:${NC}"
        docker compose -f $COMPOSE_FILE logs --since 1h web 2>/dev/null | \
            grep -i "error\|exception" | tail -5 | \
            awk '{print "  " $0}'
    fi
}

# ── Main ──────────────────────────────────────────────────
case "$1" in
    "logs")
        docker compose -f $COMPOSE_FILE logs -f
        ;;
    "errors")
        echo "=== Errors from all services (last 2h) ==="
        docker compose -f $COMPOSE_FILE logs --since 2h 2>/dev/null | \
            grep -i "error\|exception\|traceback\|fatal"
        ;;
    "stats")
        watch -n 2 "docker stats --no-stream \
            koffeecart_db koffeecart_web koffeecart_nginx"
        ;;
    *)
        print_header
        check_containers
        check_http
        check_database
        check_resources
        check_disk
        check_errors
        echo -e "\n${BLUE}══════════════════════════════════════════${NC}"
        echo -e "  Run ${YELLOW}./monitor.sh logs${NC}   → live logs"
        echo -e "  Run ${YELLOW}./monitor.sh errors${NC} → errors only"
        echo -e "  Run ${YELLOW}./monitor.sh stats${NC}  → CPU/RAM live"
        echo -e "${BLUE}══════════════════════════════════════════${NC}\n"
        ;;
esac
