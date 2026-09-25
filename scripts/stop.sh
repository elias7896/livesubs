#!/usr/bin/env bash
# ==============================================================================
# Script para Detener y Limpiar Procesos
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../requirements.txt" ]; then
    DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    DIR="$SCRIPT_DIR"
fi
cd "$DIR"

echo "Deteniendo servicios del sistema de subtitulado..."

# 1. Detener Tunel de Cloudflare
if [ -f ".tunnel.pid" ]; then
    PID=$(cat .tunnel.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo -n "   Deteniendo cloudflared (PID: $PID)... "
        kill "$PID" 2>/dev/null || true
        echo "[OK]"
    fi
    rm -f .tunnel.pid
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true

# 2. Detener Servidor FastAPI
if [ -f ".server.pid" ]; then
    PID=$(cat .server.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo -n "   Deteniendo FastAPI/Uvicorn (PID: $PID)... "
        kill "$PID" 2>/dev/null || true
        echo "[OK]"
    fi
    rm -f .server.pid
fi
pkill -f "uvicorn server:app" 2>/dev/null || true

# 3. Detener Worker en caso de que haya quedado corriendo en segundo plano
pkill -f "worker.py" 2>/dev/null || true

echo "Todos los procesos han sido detenidos limpiamente."
