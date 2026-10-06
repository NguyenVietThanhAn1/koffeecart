#!/usr/bin/env bash
# Install the backup, restore-drill and session-cleanup timers on the server.
#
#   sudo deploy/systemd/install.sh [USER]
#
# USER runs the jobs and must be allowed to use docker (default: owner of the clone).
# Check afterwards with:  systemctl list-timers 'koffeecart-*'
#                         journalctl -u koffeecart-backup.service
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }

UNIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$UNIT_DIR/../.." && pwd)"
RUN_USER=${1:-$(stat -c %U "$DEPLOY_DIR")}

id -nG "$RUN_USER" | grep -qw docker || {
    echo "User '$RUN_USER' is not in the docker group (sudo usermod -aG docker $RUN_USER)." >&2
    exit 1
}
[ -f "$DEPLOY_DIR/.env.prod" ] || { echo "Missing $DEPLOY_DIR/.env.prod" >&2; exit 1; }

for unit in "$UNIT_DIR"/*.service "$UNIT_DIR"/*.timer; do
    sed -e "s|@DEPLOY_DIR@|$DEPLOY_DIR|g" -e "s|@USER@|$RUN_USER|g" "$unit" \
        > "/etc/systemd/system/$(basename "$unit")"
done

systemctl daemon-reload
systemctl enable --now koffeecart-backup.timer koffeecart-restore-drill.timer koffeecart-clearsessions.timer
systemctl list-timers 'koffeecart-*'
echo "Installed for $RUN_USER in $DEPLOY_DIR. Run a backup now with: sudo systemctl start koffeecart-backup.service"
