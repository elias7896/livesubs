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

echo "===================================================================="
echo "STARTING LIVESUBS GATEWAY"
echo "===================================================================="

# 1. Verify Valkey Broker
echo -n "[1/3] Checking Valkey connection on localhost:6379... "
if ./venv/bin/python -c "import redis; r = redis.Redis(host='localhost', port=6379, socket_timeout=2); r.ping()" 2>/dev/null; then
    echo "[ONLINE]"
else
    echo "[OFFLINE]"
    echo "ERROR: Valkey is not reachable on port 6379."
    echo "Start Valkey with:"
    echo "  docker run -d --name valkey -p 6379:6379 valkey/valkey:7.2-alpine"
    exit 1
fi

# 2. Start FastAPI Gateway
echo "[2/3] Starting FastAPI Gateway (backend.server)..."
if [ -f ".server.pid" ] && kill -0 "$(cat .server.pid)" 2>/dev/null; then
    echo "      Server already running (PID: $(cat .server.pid))."
else
    setsid ./venv/bin/uvicorn backend.server:app --host 0.0.0.0 --port 8000 > server.log 2>&1 < /dev/null &
    SERVER_PID=$!
    echo $SERVER_PID > .server.pid
    echo "      FastAPI server started in background (PID: $SERVER_PID)."
fi

# Wait for /health endpoint
echo -n "      Waiting for server to become ready..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8000/health | grep -q "status" 2>/dev/null; then
        echo " [READY]"
        break
    fi
    sleep 0.5
done

# 3. Optional Cloudflare Tunnel
echo "[3/3] Checking Cloudflare Tunnel..."
if command -v cloudflared &>/dev/null; then
    if [ -f ".tunnel.pid" ] && kill -0 "$(cat .tunnel.pid)" 2>/dev/null; then
        echo "      Tunnel already running (PID: $(cat .tunnel.pid))."
    else
        rm -f tunnel.log
        setsid cloudflared tunnel --protocol http2 --url http://localhost:8000 > tunnel.log 2>&1 < /dev/null &
        TUNNEL_PID=$!
        echo $TUNNEL_PID > .tunnel.pid
        echo "      Cloudflare tunnel started in background (PID: $TUNNEL_PID)."
    fi

    echo -n "      Extracting public URL..."
    PUBLIC_URL=""
    for i in {1..30}; do
        if [ -f "tunnel.log" ]; then
            PUBLIC_URL=$(grep -o 'https://[-a-zA-Z0-9]*\.trycloudflare\.com' tunnel.log | head -n 1 || true)
            if [ -n "$PUBLIC_URL" ]; then
                echo " [OK]"
                break
            fi
        fi
        sleep 0.5
    done
else
    echo "      cloudflared binary not found; skipping public tunnel."
fi

# 4. Endpoints Summary
echo ""
echo "===================================================================="
echo "ACCESS ENDPOINTS"
echo "===================================================================="
echo "LOCAL NETWORK:"
echo "   - Control Room:        http://localhost:8000/dashboard"
echo "   - OBS Overlay:         http://localhost:8000/?mode=overlay"
echo "   - Web Reader:          http://localhost:8000/"
echo ""
if [ -n "$PUBLIC_URL" ]; then
    echo "PUBLIC TUNNEL:"
    echo "   - Control Room:        $PUBLIC_URL/dashboard"
    echo "   - OBS Overlay:         $PUBLIC_URL/?mode=overlay"
    echo "   - Web Reader:          $PUBLIC_URL/"
    echo ""
fi
echo "===================================================================="
echo "NEXT STEP: START AUDIO INGESTION WORKER"
echo "--------------------------------------------------------------------"
echo "Run in a separate terminal:"
echo ""
echo "   # Microphone capture:"
echo "   ./venv/bin/python backend/worker.py"
echo ""
echo "   # Live stream URL capture (YouTube, Twitch, HLS):"
echo "   ./venv/bin/python backend/worker.py --stream-url \"<STREAM_URL>\""
echo ""
echo "   # Pre-recorded audio file:"
echo "   ./venv/bin/python backend/worker.py --file /path/to/audio.wav"
echo ""
echo "To stop server and tunnel:"
echo "   ./scripts/stop.sh"
echo "===================================================================="
