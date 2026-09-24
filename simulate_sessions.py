#!/usr/bin/env python3
"""
Simulador de Sesiones Concurrentes (simulate_sessions.py) - Sprint 2
Permite simular de 3 a 5 salas de streaming en paralelo (ej. stage-1 a stage-5)
para validar:
1. Tópicos de Valkey segmentados (subtitles:{session_id}:live).
2. Persistencia acumulativa en base de datos SQLite.
3. Aislamiento de clientes WebSockets en sus respectivas salas.
4. Telemetría en vivo, alertas de silencio y exportación en el Dashboard (/dashboard).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
import redis
from dotenv import load_dotenv

load_dotenv()

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))

SAMPLE_PHRASES = [
    {
        "en": "Welcome everyone to our annual developer summit live broadcast.",
        "es": "Bienvenidos a todos a la transmisión en vivo de nuestra cumbre anual de desarrolladores."
    },
    {
        "en": "Today we are launching the new distributed real-time subtitle architecture.",
        "es": "Hoy estamos lanzando la nueva arquitectura distribuida de subtítulos en tiempo real."
    },
    {
        "en": "Notice how the latency remains consistently under one point two seconds.",
        "es": "Noten cómo la latencia se mantiene consistentemente por debajo de uno punto dos segundos."
    },
    {
        "en": "Every room and stage is completely isolated and persistent.",
        "es": "Cada sala y escenario está completamente aislado y persistente."
    },
    {
        "en": "Now let us take questions from the international audience.",
        "es": "Ahora pasemos a responder las preguntas de la audiencia internacional."
    }
]


def simulate_room_publisher(r: redis.Redis, session_id: str, count: int = 5, delay_s: float = 1.5):
    """Publica fragmentos simulados para una sala específica."""
    print(f"[Simulador] Iniciando simulación para sala '{session_id}' ({count} chunks, cada {delay_s}s)...")
    channel = f"subtitles:{session_id}:live"
    history_key = f"subtitles:{session_id}:history"

    start_sim_time = time.time()

    for seq in range(1, count + 1):
        phrase = SAMPLE_PHRASES[(seq - 1) % len(SAMPLE_PHRASES)]
        chunk_start = round((seq - 1) * 3.5, 2)
        chunk_end = round(seq * 3.5, 2)

        asr_lat = round(500.0 + (seq * 35 % 200), 1)
        trans_lat = round(320.0 + (seq * 25 % 150), 1)
        total_lat = round(asr_lat + trans_lat + 120, 1)

        payload = {
            "session_id": session_id,
            "seq": seq,
            "start_time": chunk_start,
            "end_time": chunk_end,
            "text_source": phrase["en"],
            "text_target": phrase["es"],
            "source_lang": "en",
            "target_lang": "es",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text_en": phrase["en"],
            "text_es": phrase["es"],
            "metrics": {
                "latency_ms": total_lat,
                "asr_ms": asr_lat,
                "trans_ms": trans_lat,
                "queue_ms": 15.0,
                "rpm": 12,
                "bypass": False
            }
        }

        payload_json = json.dumps(payload, ensure_ascii=False)

        # Publicar en Valkey
        pipe = r.pipeline()
        pipe.publish(channel, payload_json)
        pipe.lpush(history_key, payload_json)
        pipe.ltrim(history_key, 0, 19)
        pipe.execute()

        print(f"  [{session_id} #{seq}] Rel: {chunk_start}s-{chunk_end}s | Lat: {total_lat}ms -> {phrase['es'][:45]}...")
        if seq < count:
            time.sleep(delay_s)

    print(f"[Simulador] Simulación completada para sala '{session_id}'.")


def run_multi_room_simulation(rooms: list[str], count_per_room: int = 5, delay_s: float = 1.0):
    try:
        r = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, decode_responses=True)
        r.ping()
        print(f"Conectado a Valkey en {VALKEY_HOST}:{VALKEY_PORT}")
    except Exception as e:
        print(f"Error conectando a Valkey: {e}")
        sys.exit(1)

    print("=" * 70)
    print(f"SIMULADOR MULTISALA CONCURRENTE (Salas: {', '.join(rooms)})")
    print(f"   Chunks por sala: {count_per_room} | Retardo entre emisiones: {delay_s}s")
    print("=" * 70)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(rooms)) as executor:
        futures = [
            executor.submit(simulate_room_publisher, r, room, count_per_room, delay_s)
            for room in rooms
        ]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    print("\nTodas las salas han transmitido sus fragmentos.")
    print("Dashboard en tiempo real: http://localhost:8000/dashboard")
    print("Descarga de archivos SRT/VTT:")
    for room in rooms:
        print(f"   curl http://localhost:8000/api/sessions/{room}/export?format=srt -o {room}.srt")


def main():
    parser = argparse.ArgumentParser(description="Simulador de Salas Concurrentes (Sprint 2)")
    parser.add_argument("--rooms", nargs="+", default=["stage-1", "stage-2", "stage-3", "stage-4", "stage-5"], help="Lista de identificadores de salas")
    parser.add_argument("--chunks", type=int, default=5, help="Cantidad de chunks a emitir por sala")
    parser.add_argument("--delay", type=float, default=1.2, help="Retardo en segundos entre cada chunk")
    args = parser.parse_args()

    run_multi_room_simulation(args.rooms, args.chunks, args.delay)


if __name__ == "__main__":
    main()
