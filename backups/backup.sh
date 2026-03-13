#!/bin/bash
# ─────────────────────────────────────────────────────────
# Koffeecart Database Backup Script
# Usage: ./backup.sh           (backup now)
#        ./backup.sh restore   (list & restore)
#        ./backup.sh list      (list backups)
#        ./backup.sh clean     (remove old backups)
# ─────────────────────────────────────────────────────────

set -e

# ── Config ────────────────────────────────────────────────
PROJECT_DIR="/home/vagrant/projects/koffeecart"
BACKUP_DIR="$PROJECT_DIR/backups"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
RETENTION_DAYS=7        # Giữ backup trong 7 ngày
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/koffeecart_$TIMESTAMP.sql.gz"

# Load DB credentials từ .env.prod
source <(grep -E "^DB_" $PROJECT_DIR/.env.prod)

# ── Colors ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── Functions ─────────────────────────────────────────────

do_backup() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')] Starting backup...${NC}"

    # Kiểm tra container db đang chạy
    if ! docker compose -f $COMPOSE_FILE ps db | grep -q "Up"; then
        echo -e "${RED} Database container is not running!${NC}"
        exit 1
    fi

    # Chạy pg_dump bên trong container, nén output
    docker compose -f $COMPOSE_FILE exec -T db \
        pg_dump \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --no-password \
        --verbose \
        --format=plain \
        2>/dev/null \
    | gzip > "$BACKUP_FILE"

    # Kiểm tra file backup có tồn tại và có dung lượng không
    if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
        SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
        echo -e "${GREEN}✅ Backup successful!${NC}"
        echo -e "   File: $BACKUP_FILE"
        echo -e "   Size: $SIZE"
        echo -e "   Time: $(date '+%Y-%m-%d %H:%M:%S')"

        # Ghi log
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] BACKUP OK - $BACKUP_FILE ($SIZE)" \
            >> "$PROJECT_DIR/logs/backup.log"
    else
        echo -e "${RED}❌ Backup failed or empty file!${NC}"
        rm -f "$BACKUP_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] BACKUP FAILED" \
            >> "$PROJECT_DIR/logs/backup.log"
        exit 1
    fi

    # Tự động dọn backup cũ sau mỗi lần backup
    do_clean
}

do_clean() {
    echo -e "\n${YELLOW}[Cleanup] Removing backups older than $RETENTION_DAYS days...${NC}"

    deleted=$(find "$BACKUP_DIR" -name "*.sql.gz" \
        -mtime +$RETENTION_DAYS -type f)

    if [ -n "$deleted" ]; then
        find "$BACKUP_DIR" -name "*.sql.gz" \
            -mtime +$RETENTION_DAYS -type f -delete
        echo -e "${GREEN}  Deleted old backups:${NC}"
        echo "$deleted" | awk '{print "  - " $0}'
    else
        echo -e "  No old backups to remove."
    fi
}

do_list() {
    echo -e "${BLUE}Available backups:${NC}"
    echo "──────────────────────────────────────────"

    if ls "$BACKUP_DIR"/*.sql.gz 2>/dev/null | head -1 > /dev/null; then
        ls -lh "$BACKUP_DIR"/*.sql.gz 2>/dev/null | \
            awk '{printf "  [%s] %-40s %s\n", NR, $9, $5}'
        echo ""
        TOTAL=$(du -sh "$BACKUP_DIR" | cut -f1)
        echo -e "  Total size: ${YELLOW}$TOTAL${NC}"
    else
        echo -e "  ${YELLOW}No backups found.${NC}"
    fi
}

do_restore() {
    echo -e "${BLUE}=== Database Restore ===${NC}"
    do_list

    echo ""
    echo -n "Enter backup number to restore (or 'q' to quit): "
    read choice

    [ "$choice" = "q" ] && exit 0

    # Lấy file theo số thứ tự
    RESTORE_FILE=$(ls "$BACKUP_DIR"/*.sql.gz 2>/dev/null | sed -n "${choice}p")

    if [ -z "$RESTORE_FILE" ]; then
        echo -e "${RED}❌ Invalid selection.${NC}"
        exit 1
    fi

    echo -e "\n${YELLOW}⚠️  WARNING: This will OVERWRITE the current database!${NC}"
    echo -e "   File: $RESTORE_FILE"
    echo -n "   Are you sure? (yes/no): "
    read confirm

    if [ "$confirm" != "yes" ]; then
        echo "Cancelled."
        exit 0
    fi

    echo -e "\n${BLUE}[1/3] Dropping existing database...${NC}"
    docker compose -f $COMPOSE_FILE exec -T db \
        psql -U "$DB_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS $DB_NAME;" \
        -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

    echo -e "${BLUE}[2/3] Restoring from backup...${NC}"
    gunzip -c "$RESTORE_FILE" | \
        docker compose -f $COMPOSE_FILE exec -T db \
        psql --username="$DB_USER" --dbname="$DB_NAME"

    echo -e "${BLUE}[3/3] Running Django migrations (safety check)...${NC}"
    docker compose -f $COMPOSE_FILE exec -T web \
        python manage.py migrate --noinput

    echo -e "\n${GREEN}✅ Restore complete from: $RESTORE_FILE${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESTORE OK - from $RESTORE_FILE" \
        >> "$PROJECT_DIR/logs/backup.log"
}

# ── Main ──────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
mkdir -p "$PROJECT_DIR/logs"

case "$1" in
    "restore") do_restore ;;
    "list")    do_list ;;
    "clean")   do_clean ;;
    *)         do_backup ;;
esac
