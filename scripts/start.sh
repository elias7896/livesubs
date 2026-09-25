#!/usr/bin/env bash
# ==============================================================================
# Script de Inicio Rapido E2E - Sistema de Subtitulado y Traduccion en Vivo
# ==============================================================================

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
echo "INICIANDO SISTEMA DE SUBTITULADO Y TRADUCCION EN VIVO"
echo "===================================================================="

# 1. Verificar Broker Valkey
echo -n "[1/3] Verificando conexion a Valkey en localhost:6379... "
if ./venv/bin/python -c "import redis; r = redis.Redis(host='localhost', port=6379, socket_timeout=2); r.ping()" 2>/dev/null; then
    echo "[ONLINE]"
else
    echo "[OFFLINE]"
    echo "AVISO: Valkey no esta respondiendo en el puerto 6379."
    echo "       Asegurate de tener corriendo el contenedor Docker con:"
    echo "       docker run -d --name valkey -p 6379:6379 valkey/valkey:7.2-alpine"
    exit 1
fi

# 2. Iniciar Gateway FastAPI con Uvicorn
echo "[2/3] Iniciando Gateway WebSockets (server.py)..."
if [ -f ".server.pid" ] && kill -0 "$(cat .server.pid)" 2>/dev/null; then
    echo "      El servidor ya esta corriendo (PID: $(cat .server.pid))."
else
    setsid ./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 > server.log 2>&1 < /dev/null &
    SERVER_PID=$!
    echo $SERVER_PID > .server.pid
    echo "      Servidor FastAPI iniciado en background (PID: $SERVER_PID)."
fi

# Esperar a que el servidor este respondiendo en /health
echo -n "      Esperando a que el servidor este listo..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8000/health | grep -q "status" 2>/dev/null; then
        echo " [LISTO]"
        break
    fi
    sleep 0.5
done

# 3. Iniciar Tunel de Cloudflare
echo "[3/3] Iniciando Tunel Publico con Cloudflare..."
if [ -f ".tunnel.pid" ] && kill -0 "$(cat .tunnel.pid)" 2>/dev/null; then
    echo "      El tunel ya esta corriendo (PID: $(cat .tunnel.pid))."
else
    rm -f tunnel.log
    setsid cloudflared tunnel --protocol http2 --url http://localhost:8000 > tunnel.log 2>&1 < /dev/null &
    TUNNEL_PID=$!
    echo $TUNNEL_PID > .tunnel.pid
    echo "      Tunel cloudflared iniciado en background (PID: $TUNNEL_PID)."
fi

# Extraer URL publica de Cloudflare de los logs
echo -n "      Generando URL publica https://*.trycloudflare.com..."
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

if [ -z "$PUBLIC_URL" ]; then
    echo " [AVISO: no se pudo extraer automaticamente de tunnel.log]"
fi

# 4. Mostrar Panel de Enlaces y URLs
echo ""
echo "===================================================================="
echo "PANEL DE ACCESO Y ENLACES (MULTI-CLIENTE)"
echo "===================================================================="
echo "RED LOCAL (Tu maquina o misma red WiFi):"
echo "   - Control Room:        http://localhost:8000/controlroom"
echo "   - Modo Overlay OBS:    http://localhost:8000/?mode=overlay"
echo "   - Modo Lector Web:     http://localhost:8000/"
echo ""
if [ -n "$PUBLIC_URL" ]; then
    echo "INTERNET PUBLICA (Movil, Remoto u OBS externo):"
    echo "   - Control Room:        $PUBLIC_URL/controlroom"
    echo "   - Modo Overlay OBS:    $PUBLIC_URL/?mode=overlay"
    echo "   - Modo Lector Web:     $PUBLIC_URL/"
    echo ""
fi
echo "===================================================================="
echo "PASO SIGUIENTE: INICIAR EL WORKER DE AUDIO"
echo "--------------------------------------------------------------------"
echo "Para capturar audio y transmitir en vivo, corre en otra terminal:"
echo ""
echo "   # Opcion A (Tu Microfono en vivo):"
echo "   ./venv/bin/python worker.py"
echo ""
echo "   # Opcion B (Prueba con Audio WAV pregrabado):"
echo "   ./venv/bin/python worker.py --file sample_jfk.wav"
echo ""
echo "Para apagar el servidor y el tunel al finalizar, ejecuta:"
echo "   ./stop.sh"
echo "===================================================================="
