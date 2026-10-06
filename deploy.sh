#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Koffeecart production deploy
#
# Usage:
#   ./deploy.sh <tag>            pull image WEB_IMAGE:<tag> (e.g. sha-1a2b3c4) and deploy it
#   ./deploy.sh --build          git pull, build locally, deploy (before CI pushes images)
#   ./deploy.sh --rollback       redeploy the previously deployed tag
#
# Needs .env.prod. Set WEB_IMAGE (e.g. annguyn0810/koffeecart) when pulling from a registry.
# ─────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose --env-file .env.prod -f docker-compose.prod.yml)
CURRENT_FILE=.deploy_current   # tag currently deployed (git-ignored)
PREVIOUS_FILE=.deploy_previous # tag deployed before that

CURRENT_TAG=$(cat "$CURRENT_FILE" 2>/dev/null || true)
PREVIOUS_TAG=$(cat "$PREVIOUS_FILE" 2>/dev/null || true)

wait_healthy() {
    # $1 = container name; wait up to 120s for Docker healthcheck to say "healthy"
    local name=$1 status
    for _ in $(seq 1 60); do
        status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo missing)
        [ "$status" = "healthy" ] && return 0
        sleep 2
    done
    echo "  $name is '$status' after 120s"
    return 1
}

deploy_tag() {
    # $1 = image tag. Returns non-zero if the stack does not become healthy.
    export IMAGE_TAG=$1
    "${COMPOSE[@]}" up -d --remove-orphans   # no "down": containers are replaced in place
    wait_healthy koffeecart_web && wait_healthy koffeecart_nginx \
        && curl -fsS http://localhost/health/ > /dev/null
}

case "${1:-}" in
    ""|-h|--help)
        sed -n '2,11p' "$0"; exit 1 ;;
    --rollback)
        [ -n "$PREVIOUS_TAG" ] || { echo "No previous tag recorded."; exit 1; }
        NEW_TAG=$PREVIOUS_TAG
        echo "Rolling back to $NEW_TAG"
        ;;
    --build)
        # The CI deploy leaves the clone on a detached commit, where "git pull" fails, so
        # fetch and check out origin/main explicitly. No --force: local edits stop the deploy.
        git fetch origin main
        git checkout --detach origin/main
        NEW_TAG="local-$(git rev-parse --short HEAD)"
        echo "Building image tag $NEW_TAG"
        IMAGE_TAG=$NEW_TAG "${COMPOSE[@]}" build web
        ;;
    *)
        NEW_TAG=$1
        echo "Pulling image tag $NEW_TAG"
        IMAGE_TAG=$NEW_TAG "${COMPOSE[@]}" pull web
        ;;
esac

echo "Deploying $NEW_TAG (current: ${CURRENT_TAG:-none})"
if deploy_tag "$NEW_TAG"; then
    if [ "$NEW_TAG" != "$CURRENT_TAG" ]; then
        [ -n "$CURRENT_TAG" ] && echo "$CURRENT_TAG" > "$PREVIOUS_FILE"
        echo "$NEW_TAG" > "$CURRENT_FILE"
    fi
    echo "Deployment OK: $NEW_TAG"
    "${COMPOSE[@]}" ps
    exit 0
fi

echo "Health check FAILED for $NEW_TAG"
"${COMPOSE[@]}" logs --tail=50 web || true
if [ -n "$CURRENT_TAG" ] && [ "$CURRENT_TAG" != "$NEW_TAG" ]; then
    echo "Rolling back to $CURRENT_TAG"
    if deploy_tag "$CURRENT_TAG"; then
        echo "Rolled back to $CURRENT_TAG. Note: database migrations are NOT reverted."
    else
        echo "Rollback also failed. Manual intervention needed."
    fi
else
    echo "No earlier tag to roll back to."
fi
exit 1
