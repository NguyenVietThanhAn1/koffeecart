#!/bin/bash
# ─────────────────────────────────────────────────────────
# Koffeecart Production Deploy Script
# Usage: ./deploy.sh
# ─────────────────────────────────────────────────────────

set -e  # Exit immediately on any error

PROJECT_DIR="/home/vagrant/projects/koffeecart"
COMPOSE_FILE="docker-compose.prod.yml"

echo "======================================"
echo "  Koffeecart Deployment - $(date)"
echo "======================================"

cd $PROJECT_DIR

# ── Step 1: Pull latest code ──────────────────
echo "[1/5] Pulling latest code from GitHub..."
git pull origin main

# ── Step 2: Rebuild images ────────────────────
echo "[2/5] Building Docker images..."
docker compose -f $COMPOSE_FILE build --no-cache

# ── Step 3: Stop old containers ───────────────
echo "[3/5] Stopping current containers..."
docker compose -f $COMPOSE_FILE down

# ── Step 4: Start new containers ──────────────
echo "[4/5] Starting production stack..."
docker compose -f $COMPOSE_FILE up -d

# ── Step 5: Health check ──────────────────────
echo "[5/5] Running health check..."
sleep 10

if curl -f -s http://localhost > /dev/null; then
    echo ""
    echo "✅ Deployment successful!"
    echo "   App: http://localhost"
    echo "======================================"
else
    echo ""
    echo "❌ Health check failed! Rolling back..."
    docker compose -f $COMPOSE_FILE logs --tail=50
    exit 1
fi

# Show running containers
docker compose -f $COMPOSE_FILE ps
