#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../requirements.txt" ]; then
    DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    DIR="$SCRIPT_DIR"
fi
cd "$DIR"

echo "Stopping LiveSubs services..."

# 1. Stop Cloudflare Tunnel
if [ -f ".tunnel.pid" ]; then
    PID=$(cat .tunnel.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo -n "   Stopping cloudflared (PID: $PID)... "
        kill "$PID" 2>/dev/null || true
        echo "[OK]"
    fi
    rm -f .tunnel.pid
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true

# 2. Stop FastAPI Gateway
if [ -f ".server.pid" ]; then
    PID=$(cat .server.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo -n "   Stopping FastAPI / Uvicorn (PID: $PID)... "
        kill "$PID" 2>/dev/null || true
        echo "[OK]"
    fi
    rm -f .server.pid
fi
pkill -f "uvicorn.*server:app" 2>/dev/null || true

# 3. Stop background workers
pkill -f "worker.py" 2>/dev/null || true

echo "All services stopped."
