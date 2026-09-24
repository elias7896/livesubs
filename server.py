#!/usr/bin/env python3
"""
Gateway de Distribución WebSockets y Monitoreo Audiovisual (server.py) - Sprint 2
Soporta:
1. Arquitectura multisesión concurrente (salas en paralelo e.g. /ws/{session_id}).
2. Persistencia acumulativa en SQLite (database.py) para cada subtítulo emitido.
3. Exportación completa de subtítulos en formatos estándar (SRT, WebVTT, TXT).
4. Dashboard de monitoreo en tiempo real (/dashboard) con telemetría SSE (/api/telemetry/stream).
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional, List

import re
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel
import redis.asyncio as aioredis

from database import db
import exporters

# Cargar variables de entorno
load_dotenv()

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

# Rutas de Archivos Estáticos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SERVER] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("server")

# Parámetros de Configuración
VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_CHANNEL = os.getenv("VALKEY_CHANNEL", "subtitles:live")
VALKEY_HISTORY_KEY = os.getenv("VALKEY_HISTORY_KEY", "subtitles:history")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Configuración de Groq para traducción On-Demand
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEYS_RAW = os.getenv("GROQ_API_KEYS", "") or GROQ_API_KEY
GROQ_API_KEYS = [k.strip() for k in GROQ_API_KEYS_RAW.split(",") if k.strip()]
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
groq_client = Groq(api_key=GROQ_API_KEYS[0]) if GROQ_API_KEYS else None

translation_cache: Dict[str, str] = {}


def sync_translate_batch(texts: List[str], target_lang: str = "pt") -> List[str]:
    """Traduce un lote de oraciones al idioma de destino utilizando Groq con JSON estructurado."""
    if not texts:
        return []
    if not groq_client:
        return texts

    target_norm = (target_lang or "pt").lower().strip()
    target_names = {
        "en": "English",
        "es": "Spanish",
        "pt": "Portuguese"
    }
    tgt_name = target_names.get(target_norm, target_norm.capitalize())

    system_prompt = (
        f"You are a professional real-time live conference interpreter. Translate the given array of sentences into {tgt_name}. "
        "IMPORTANT: PRESERVE software engineering, DevOps, cloud, and streaming technical terms intact in their standard English industry terminology. "
        "Output MUST be a valid JSON object with the key 'translations', containing the translated array of strings in the exact same order as the input array. "
        "Format: {\"translations\": [\"...\", \"...\"]}. "
        "Output ONLY valid JSON without markdown fences, comments, or explanations."
    )

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        parsed = json.loads(content)
        translations = parsed.get("translations", [])
        if isinstance(translations, list) and len(translations) == len(texts):
            return [str(t) for t in translations]
        elif isinstance(translations, list) and len(translations) > 0:
            res = [str(t) for t in translations]
            while len(res) < len(texts):
                res.append(texts[len(res)])
            return res[:len(texts)]
    except Exception as e:
        logger.warning(f"Error en traducción batch Groq: {e}")

    return texts


async def translate_texts_batch(texts: List[str], target_lang: str = "pt", source_lang: str = "auto") -> List[str]:
    """Traduce un lote de textos con soporte de caché en memoria para latencia cero en textos repetidos."""
    target_norm = (target_lang or "pt").lower().strip()
    uncached_indices = []
    uncached_texts = []
    results: List[Optional[str]] = [None] * len(texts)

    for idx, text in enumerate(texts):
        cleaned = text.strip()
        if not cleaned:
            results[idx] = text
            continue
        cache_key = f"{target_norm}:{cleaned}"
        if cache_key in translation_cache:
            results[idx] = translation_cache[cache_key]
        else:
            uncached_indices.append(idx)
            uncached_texts.append(cleaned)

    if uncached_texts:
        translated_list = await asyncio.to_thread(sync_translate_batch, uncached_texts, target_norm)
        for idx, trans_text in zip(uncached_indices, translated_list):
            orig = texts[idx].strip()
            cache_key = f"{target_norm}:{orig}"
            translation_cache[cache_key] = trans_text
            results[idx] = trans_text

    return [r if r is not None else texts[i] for i, r in enumerate(results)]


class ConnectionManager:
    """
    Gestor concurrente de conexiones WebSockets con soporte para múltiples salas (rooms/session_id).
    Permite aislar transmisiones entre salas sin interferencia cruzada.
    """

    def __init__(self):
        self.rooms: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.ws_to_room: Dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str = "main"):
        """Acepta y registra una conexión en una sala específica."""
        await websocket.accept()
        norm_session = session_id.lower().strip()
        async with self._lock:
            self.rooms[norm_session].add(websocket)
            self.ws_to_room[websocket] = norm_session
        logger.info(f"Cliente conectado en sala '{norm_session}' ({websocket.client}). Total en sala: {len(self.rooms[norm_session])}")

    async def disconnect(self, websocket: WebSocket):
        """Remueve la conexión de su sala de forma segura."""
        async with self._lock:
            session_id = self.ws_to_room.pop(websocket, None)
            if session_id and session_id in self.rooms:
                self.rooms[session_id].discard(websocket)
                if not self.rooms[session_id]:
                    del self.rooms[session_id]
        logger.info(f"Cliente desconectado de sala '{session_id or 'unknown'}' ({websocket.client})")

    def get_viewer_count(self, session_id: Optional[str] = None) -> int:
        """Obtiene la cantidad de espectadores conectados a una sala o global."""
        if session_id:
            return len(self.rooms.get(session_id.lower().strip(), set()))
        return sum(len(clients) for clients in self.rooms.values())

    async def broadcast_to_session(self, session_id: str, message: str | dict):
        """
        Retransmite en paralelo exclusivamente a los clientes suscritos a esa sesión.
        """
        norm_session = session_id.lower().strip()
        async with self._lock:
            clients = list(self.rooms.get(norm_session, set()))

        if not clients:
            return

        text_data = json.dumps(message, ensure_ascii=False) if isinstance(message, dict) else message

        async def _send(ws: WebSocket):
            try:
                await ws.send_text(text_data)
                return None
            except (WebSocketDisconnect, RuntimeError, Exception):
                return ws

        failed_clients = await asyncio.gather(*[_send(ws) for ws in clients], return_exceptions=False)
        for ws in failed_clients:
            if ws is not None:
                await self.disconnect(ws)


class TelemetryTracker:
    """
    Seguimiento en memoria del estado y métricas de cada sala para el Dashboard Audiovisual.
    """

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def update(self, session_id: str, data: Dict[str, Any]):
        sid = session_id.lower().strip()
        now = time.time()
        async with self._lock:
            existing = self._sessions.get(sid, {
                "session_id": sid,
                "title": f"Sala {sid.capitalize()}",
                "status": "live",
                "source_lang": data.get("source_lang", "en"),
                "target_lang": data.get("target_lang", "es"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "subtitles_count": 0,
            })
            if existing.get("status") == "closed":
                return

            metrics = data.get("metrics") or {}
            existing["last_activity"] = now
            existing["last_seq"] = data.get("seq", existing.get("subtitles_count", 0) + 1)
            existing["subtitles_count"] = existing.get("subtitles_count", 0) + 1
            audio_chunk_dur = float(metrics.get("audio_duration_s") or 0.0)
            end_t = float(data.get("end_time") or 0.0)
            existing["duration_seconds"] = max(
                existing.get("duration_seconds", 0.0) + (audio_chunk_dur if audio_chunk_dur > 0 else 3.0),
                end_t
            )
            existing["source_lang"] = data.get("source_lang", existing.get("source_lang", "en"))
            existing["target_lang"] = data.get("target_lang", existing.get("target_lang", "es"))
            existing["last_text_source"] = data.get("text_source", "")
            existing["last_text_target"] = data.get("text_target", "")
            existing["last_timestamp"] = data.get("timestamp", datetime.now(timezone.utc).isoformat())
            existing["metrics"] = {
                "latency_ms": metrics.get("latency_ms", 0),
                "asr_ms": metrics.get("asr_ms", 0),
                "trans_ms": metrics.get("trans_ms", 0),
                "queue_ms": metrics.get("queue_ms", 0),
                "rpm": metrics.get("rpm", 0),
                "bypass": metrics.get("bypass", False)
            }

            self._sessions[sid] = existing

    async def register_session(self, session_id: str, title: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None, stream_url: Optional[str] = None):
        sid = session_id.lower().strip()
        async with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = {
                    "session_id": sid,
                    "title": title or f"Sala {sid.capitalize()}",
                    "status": "active",
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "stream_url": stream_url,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_activity": time.time(),
                    "subtitles_count": 0,
                    "duration_seconds": 0.0,
                    "last_seq": 0,
                    "last_text_source": "",
                    "last_text_target": "",
                    "metrics": {
                        "latency_ms": 0,
                        "asr_ms": 0,
                        "trans_ms": 0,
                        "rpm": 0
                    }
                }
            else:
                self._sessions[sid]["status"] = "active"
                self._sessions[sid]["last_activity"] = time.time()
                if stream_url:
                    self._sessions[sid]["stream_url"] = stream_url

    async def mark_active(self, session_id: str):
        sid = session_id.lower().strip()
        async with self._lock:
            if sid in self._sessions:
                self._sessions[sid]["status"] = "active"
                self._sessions[sid]["last_activity"] = time.time()

    async def mark_closed(self, session_id: str):
        sid = session_id.lower().strip()
        async with self._lock:
            if sid in self._sessions:
                self._sessions[sid]["status"] = "closed"
                self._sessions[sid]["metrics"] = {
                    "latency_ms": 0,
                    "asr_ms": 0,
                    "trans_ms": 0,
                    "rpm": 0
                }

    async def remove_session(self, session_id: str):
        sid = session_id.lower().strip()
        async with self._lock:
            self._sessions.pop(sid, None)

    async def get_all_snapshots(self, manager: ConnectionManager) -> list[Dict[str, Any]]:
        now = time.time()
        snapshots = []
        async with self._lock:
            # Sincronizar con sesiones en base de datos de manera resiliente
            try:
                db_sessions = await db.list_sessions()
            except Exception as e:
                logger.error(f"Error consultando sesiones en DB: {e}")
                db_sessions = []
            db_sessions_map = {s["session_id"]: s for s in db_sessions}

            all_ids = set(self._sessions.keys()).union(set(db_sessions_map.keys()))

            for sid in sorted(all_ids):
                item = self._sessions.get(sid)
                db_item = db_sessions_map.get(sid, {})

                if not item:
                    item = {
                        "session_id": sid,
                        "title": db_item.get("title") or f"Sala {sid.capitalize()}",
                        "status": db_item.get("status", "active"),
                        "source_lang": db_item.get("source_lang", "en"),
                        "target_lang": db_item.get("target_lang", "es"),
                        "stream_url": db_item.get("stream_url"),
                        "created_at": db_item.get("created_at", datetime.now(timezone.utc).isoformat()),
                        "last_activity": 0,
                        "subtitles_count": db_item.get("total_subtitles", 0),
                        "duration_seconds": float(db_item.get("duration_seconds") or 0.0),
                        "last_seq": db_item.get("total_subtitles", 0),
                        "last_text_source": "",
                        "last_text_target": "",
                        "metrics": {
                            "latency_ms": round(db_item.get("avg_latency_ms") or 0, 0),
                            "asr_ms": 0,
                            "trans_ms": 0,
                            "rpm": 0
                        }
                    }

                # Cálculo de estado reactivo y alerta de silencio (>15s)
                last_act = item.get("last_activity", 0)
                elapsed = now - last_act if last_act > 0 else 9999
                raw_status = item.get("status", "active")
                is_worker_active = stream_manager.is_running(sid)

                if raw_status == "closed":
                    computed_status = "closed"
                elif is_worker_active:
                    computed_status = "live"
                elif last_act > 0 and elapsed <= 60:
                    computed_status = "live"
                else:
                    computed_status = "active"

                snapshot = dict(item)
                db_dur = float(db_item.get("duration_seconds") or 0.0) if db_item else 0.0
                total_dur = max(float(item.get("duration_seconds", 0.0)), db_dur)
                snapshot["duration_seconds"] = round(total_dur, 1)
                snapshot["audio_minutes"] = round(total_dur / 60.0, 2)
                snapshot["status"] = computed_status
                snapshot["viewers"] = manager.get_viewer_count(sid)
                snapshot["silence_duration_s"] = round(elapsed, 1) if elapsed < 9000 else None
                snapshot["stream_url"] = item.get("stream_url") or db_item.get("stream_url")
                snapshot["is_stream"] = stream_manager.is_running(sid) or bool(snapshot["stream_url"])
                snapshots.append(snapshot)

        return snapshots


class StreamWorkerManager:
    """Administrador de subprocesos worker para ingesta automática de streams online (YouTube, Twitch, Kick, HLS)."""

    def __init__(self):
        self.workers: Dict[str, subprocess.Popen] = {}
        self._lock = asyncio.Lock()

    async def start_worker(self, session_id: str, stream_url: str, source_lang: str = "en", target_lang: str = "es", is_live: bool = False) -> bool:
        sid = session_id.lower().strip()
        await self.stop_worker(sid)

        venv_python = os.path.join(BASE_DIR, "venv", "bin", "python")
        python_bin = venv_python if os.path.exists(venv_python) else sys.executable
        worker_script = os.path.join(BASE_DIR, "worker.py")
        cmd = [
            python_bin,
            worker_script,
            "--session-id", sid,
            "--source-lang", source_lang,
            "--target-lang", target_lang,
            "--stream-url", stream_url
        ]
        if is_live:
            cmd.append("--is-live")

        logger.info(f"Despachando worker de stream para sala '{sid}' (URL: {stream_url}, Live: {is_live})...")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            async with self._lock:
                self.workers[sid] = proc

            # Reenviar logs del subproceso worker al logger del servidor
            def _log_forwarder(p: subprocess.Popen, room: str):
                try:
                    for line in iter(p.stdout.readline, ""):
                        if line:
                            logger.info(f"[{room.upper()}-STREAM] {line.strip()}")
                except Exception:
                    pass

            t = threading.Thread(target=_log_forwarder, args=(proc, sid), daemon=True)
            t.start()
            return True
        except Exception as e:
            logger.error(f"Fallo al iniciar worker de stream para '{sid}': {e}")
            return False

    async def stop_worker(self, session_id: str) -> bool:
        sid = session_id.lower().strip()
        async with self._lock:
            proc = self.workers.pop(sid, None)

        if proc:
            if proc.poll() is None:
                logger.info(f"Deteniendo worker de stream '{sid}' (PID: {proc.pid})...")
                try:
                    proc.terminate()
                    await asyncio.to_thread(proc.wait, timeout=3.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            return True
        return False

    def is_running(self, session_id: str) -> bool:
        sid = session_id.lower().strip()
        proc = self.workers.get(sid)
        return proc is not None and proc.poll() is None

    async def stop_all(self):
        async with self._lock:
            all_sids = list(self.workers.keys())
        for sid in all_sids:
            await self.stop_worker(sid)


# Instancias globales
manager = ConnectionManager()
stream_manager = StreamWorkerManager()
telemetry = TelemetryTracker()
valkey_client: Optional[aioredis.Redis] = None


async def valkey_pubsub_listener(app: FastAPI):
    """
    Escucha continua de canales en Valkey Pub/Sub (subtitles:*).
    1. Segmenta por session_id.
    2. Persiste acumulativamente cada fragmento en SQLite.
    3. Actualiza telemetría para el Dashboard en tiempo real.
    4. Retransmite a los WebSockets de la sesión correspondiente.
    """
    current_valkey: aioredis.Redis = getattr(app.state, "valkey", valkey_client)
    logger.info("Iniciando suscriptor Pattern Valkey para todas las salas ('subtitles:*:live')...")

    # Caché circular de deduplicación para evitar procesar o retransmitir fragmentos duplicados
    seen_messages = deque(maxlen=1000)
    seen_set = set()

    while True:
        pubsub = None
        try:
            pubsub = current_valkey.pubsub()
            await pubsub.psubscribe("subtitles:*:live", "subtitles:live")
            logger.info("Suscripción activa a Valkey Pattern: 'subtitles:*:live'")

            async for msg in pubsub.listen():
                if msg["type"] in ("message", "pmessage"):
                    raw_channel = msg.get("channel", "")
                    if isinstance(raw_channel, bytes):
                        raw_channel = raw_channel.decode("utf-8", errors="ignore")
                    
                    # Solo procesar canales canónicos de emisión en vivo
                    if not raw_channel.endswith(":live"):
                        continue

                    raw_data = msg["data"]
                    try:
                        payload = json.loads(raw_data)
                        if not isinstance(payload, dict):
                            continue

                        session_id = payload.get("session_id", "").lower().strip()
                        if not session_id:
                            continue

                        seq = payload.get("seq", 1)

                        # Deduplicación por mensaje único recibido en Valkey (evita duplicados si el broker reentrega)
                        msg_ts = payload.get("timestamp", "")
                        dedup_key = f"{session_id}:{seq}:{msg_ts}"
                        if dedup_key in seen_set:
                            continue
                        seen_set.add(dedup_key)
                        seen_messages.append(dedup_key)
                        if len(seen_set) > 1200:
                            seen_set = set(seen_messages)

                        start_time = payload.get("start_time", 0.0)
                        end_time = payload.get("end_time", 0.0)
                        text_source = payload.get("text_source") or payload.get("text_en") or ""
                        text_target = payload.get("text_target") or payload.get("text_es") or text_source
                        source_lang = payload.get("source_lang", "en")
                        target_lang = payload.get("target_lang", "es")
                        translations = payload.get("translations") or {}
                        text_pt = payload.get("text_pt") or (translations.get("pt") if isinstance(translations, dict) else None)

                        # 1. Almacenamiento acumulativo persistente en SQLite
                        try:
                            metrics = payload.get("metrics") or {}
                            await db.add_subtitle(
                                session_id=session_id,
                                seq=seq,
                                start_time=start_time,
                                end_time=end_time,
                                text_source=text_source,
                                text_target=text_target,
                                source_lang=source_lang,
                                target_lang=target_lang,
                                latency_ms=metrics.get("latency_ms", 0.0),
                                asr_ms=metrics.get("asr_ms", 0.0),
                                trans_ms=metrics.get("trans_ms", 0.0),
                                translations=translations,
                                text_pt=text_pt
                            )
                        except Exception as e:
                            logger.error(f"Error persistiendo subtítulo en SQLite: {e}")

                        # 2. Actualizar estado de telemetría para el Dashboard
                        await telemetry.update(session_id, payload)

                        # 3. Retransmisión aislada a los clientes de esta sala
                        payload["type"] = "live"
                        await manager.broadcast_to_session(session_id, payload)

                    except Exception as e:
                        logger.error(f"Error procesando mensaje de Valkey: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Listener de Valkey cancelado.")
            if pubsub:
                try:
                    await pubsub.punsubscribe("subtitles:*")
                    if hasattr(pubsub, "aclose"):
                        await pubsub.aclose()
                    else:
                        await pubsub.close()
                except Exception:
                    pass
            break
        except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
            logger.warning(f"Desconexión temporal de Valkey: {e}. Reintentando en 2s...")
            if pubsub:
                try:
                    await pubsub.close()
                except Exception:
                    pass
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Excepción en listener de Valkey: {e}", exc_info=True)
            if pubsub:
                try:
                    await pubsub.close()
                except Exception:
                    pass
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de FastAPI: inicializa clientes, DB y tareas de fondo."""
    global valkey_client

    valkey_client = aioredis.Redis(
        host=VALKEY_HOST,
        port=VALKEY_PORT,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5
    )
    app.state.valkey = valkey_client
    app.state.manager = manager
    app.state.telemetry = telemetry

    listener_task = asyncio.create_task(valkey_pubsub_listener(app))
    logger.info("Gateway WebSockets & Observabilidad iniciado.")

    try:
        yield
    finally:
        logger.info("Deteniendo Gateway...")
        await stream_manager.stop_all()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        if valkey_client:
            await valkey_client.aclose()
        logger.info("Recursos de servidor cerrados con éxito.")


# Aplicación FastAPI
app = FastAPI(
    title="Live Subtitles & Multi-Room Audio Gateway",
    description="Gateway WebSocket para distribución de subtítulos en vivo y observabilidad (Sprint 2)",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# -----------------------------------------------------------------------------
# Rutas de Frontend (Lector, Overlay y Dashboard)
# -----------------------------------------------------------------------------

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0"
}


@app.get("/", response_class=FileResponse)
async def serve_reader_page():
    """Modo Lector Web (admite ?session=stage-1)."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=NO_CACHE_HEADERS)


@app.get("/fullscreen", response_class=FileResponse)
async def serve_fullscreen_page():
    """Modo Fullscreen / Pantalla Completa nativo."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=NO_CACHE_HEADERS)


@app.get("/overlay", response_class=FileResponse)
async def serve_overlay_page():
    """Modo Overlay para OBS Studio (admite ?mode=overlay&session=stage-1)."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=NO_CACHE_HEADERS)


@app.get("/controlroom", response_class=FileResponse)
@app.get("/control", response_class=FileResponse)
@app.get("/control-room", response_class=FileResponse)
@app.get("/dashboard", response_class=FileResponse)
async def serve_dashboard_page():
    """Dashboard de Monitoreo Audiovisual y Control Room."""
    dashboard_file = os.path.join(STATIC_DIR, "dashboard.html")
    if os.path.exists(dashboard_file):
        return FileResponse(dashboard_file, headers=NO_CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="Dashboard UI no encontrado.")


@app.get("/health")
async def health_check():
    """Chequeo de salud del servicio y componentes."""
    valkey_ok = False
    if valkey_client:
        try:
            valkey_ok = await valkey_client.ping()
        except Exception:
            valkey_ok = False

    return {
        "status": "healthy" if valkey_ok else "degraded",
        "active_viewers": manager.get_viewer_count(),
        "active_rooms": len(manager.rooms),
        "valkey_connected": valkey_ok,
        "database": "sqlite_wal"
    }


# -----------------------------------------------------------------------------
# Endpoints REST de Sesiones y Exportación (Objetivo 4)
# -----------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    session_id: str
    title: Optional[str] = None
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    stream_url: Optional[str] = None


class StartStreamRequest(BaseModel):
    stream_url: str


class TranslateBatchRequest(BaseModel):
    texts: List[str]
    target_lang: str = "pt"
    source_lang: Optional[str] = "auto"


@app.post("/api/translate")
async def translate_endpoint(req: TranslateBatchRequest):
    """Traduce un lote de textos de forma instantánea on-demand."""
    if not req.texts:
        return {"translations": [], "target_lang": req.target_lang}
    translated = await translate_texts_batch(req.texts, target_lang=req.target_lang, source_lang=req.source_lang)
    return {"translations": translated, "target_lang": req.target_lang}


@app.get("/api/sessions")
async def get_sessions():
    """Lista todas las sesiones registradas con sus métricas acumuladas."""
    snapshots = await telemetry.get_all_snapshots(manager)
    return {"sessions": snapshots}


@app.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    """Crea o da de alta una nueva sesión o transmisión interactiva con ingesta de stream opcional."""
    sid = req.session_id.lower().strip()
    if not sid:
        raise HTTPException(status_code=400, detail="El ID de sesión no puede estar vacío.")

    if not re.match(r'^[a-zA-Z0-9_\-]+$', sid):
        raise HTTPException(
            status_code=400,
            detail="El ID de sesión solo puede contener letras, números, guiones (-) y guiones bajos (_)."
        )

    title = (req.title or "").strip() or f"Sala {sid.capitalize()}"
    src = (req.source_lang or "").lower().strip() or None
    tgt = (req.target_lang or "").lower().strip() or None
    stream_url = (req.stream_url or "").strip() or None

    session_row = await db.get_or_create_session(
        session_id=sid,
        source_lang=src,
        target_lang=tgt,
        title=title,
        stream_url=stream_url
    )
    await telemetry.register_session(sid, title, src, tgt, stream_url=stream_url)

    # Si se especificó URL de stream, iniciar subproceso de ingesta automática
    if stream_url:
        await stream_manager.start_worker(
            session_id=sid,
            stream_url=stream_url,
            source_lang=src or "auto",
            target_lang=tgt or "es"
        )

    return {"status": "created", "session": session_row, "has_stream_worker": bool(stream_url)}


@app.post("/api/sessions/{session_id}/start-stream")
async def start_session_stream(session_id: str, req: StartStreamRequest):
    """Inicia o reconecta la ingesta de un stream online para una sesión existente."""
    sid = session_id.lower().strip()
    url = (req.stream_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="La URL del stream no puede estar vacía.")

    session_row = await db.get_or_create_session(sid, stream_url=url)
    existing_tel = telemetry._sessions.get(sid, {})
    src = session_row.get("source_lang") or existing_tel.get("source_lang") or "auto"
    tgt = session_row.get("target_lang") or existing_tel.get("target_lang") or "es"
    await telemetry.register_session(sid, session_row.get("title") or sid, src if src != "auto" else None, tgt, stream_url=url)
    success = await stream_manager.start_worker(sid, url, src, tgt)
    return {"status": "started" if success else "failed", "session_id": sid, "stream_url": url}


@app.post("/api/sessions/{session_id}/stop-stream")
async def stop_session_stream(session_id: str):
    """Detiene el subproceso de ingesta de stream de una sesión sin cerrarla."""
    sid = session_id.lower().strip()
    stopped = await stream_manager.stop_worker(sid)
    return {"status": "stopped", "session_id": sid, "was_running": stopped}


@app.post("/api/sessions/{session_id}/close")
async def close_session(session_id: str):
    """Cierra/pausa formalmente una sesión de subtitulado (pasa a Inactiva) y apaga su worker de stream si existía."""
    sid = session_id.lower().strip()
    await stream_manager.stop_worker(sid)
    success = await db.close_session(sid)
    await telemetry.mark_closed(sid)
    return {"status": "closed", "session_id": sid, "success": success}


@app.post("/api/sessions/{session_id}/resume")
async def resume_session(session_id: str):
    """Reactiva una sesión pausada/inactiva y reinicia su worker de stream si tenía URL."""
    sid = session_id.lower().strip()
    session_row = await db.get_or_create_session(sid)
    existing_tel = telemetry._sessions.get(sid, {})
    src = session_row.get("source_lang") or existing_tel.get("source_lang") or "auto"
    tgt = session_row.get("target_lang") or existing_tel.get("target_lang") or "es"
    stream_url = session_row.get("stream_url") or existing_tel.get("stream_url")
    title = session_row.get("title") or f"Sala {sid.capitalize()}"
    success = await db.resume_session(sid)
    await telemetry.register_session(sid, title, src if src != "auto" else None, tgt, stream_url=stream_url)
    has_worker = False
    if stream_url:
        has_worker = await stream_manager.start_worker(sid, stream_url, src, tgt)
    return {"status": "active", "session_id": sid, "success": success, "has_worker": has_worker}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Elimina permanentemente una sesión, apaga su worker y borra sus datos."""
    sid = session_id.lower().strip()
    await stream_manager.stop_worker(sid)
    success = await db.delete_session(sid)
    await telemetry.remove_session(sid)
    return {"status": "deleted", "session_id": sid, "success": success}


@app.get("/api/sessions/{session_id}/export")
async def export_session_subtitles(
    session_id: str,
    format: str = Query("srt", pattern="^(srt|vtt|txt)$"),
    bilingual: bool = Query(True, description="Incluir ambos idiomas si están disponibles"),
    prefer_source: bool = Query(False, description="Priorizar idioma original")
):
    """
    Descarga la transcripción acumulada completa en formatos SRT, WebVTT o TXT.
    Solo permitido cuando la sesión ha finalizado (inactiva).
    """
    sid = session_id.lower().strip()

    # Validar que la sesión no esté transmitiendo en vivo para no saturar el servidor
    live_session = telemetry._sessions.get(sid)
    if live_session and live_session.get("status") in ("live", "silent"):
        raise HTTPException(
            status_code=400,
            detail="La exportación de archivos solo está permitida una vez finalizada la sesión (estado Inactiva)."
        )

    subtitles = await db.get_subtitles(sid)

    if not subtitles:
        # Intentar crear archivo vacío si no hay registros
        subtitles = []

    format_lower = format.lower()
    if format_lower == "srt":
        content = exporters.generate_srt(subtitles, bilingual=bilingual, prefer_source=prefer_source)
        media_type = "application/x-subrip"
        filename = f"subtitles_{sid}.srt"
    elif format_lower == "vtt":
        content = exporters.generate_vtt(subtitles, bilingual=bilingual, prefer_source=prefer_source)
        media_type = "text/vtt"
        filename = f"subtitles_{sid}.vtt"
    else:  # txt
        content = exporters.generate_txt(subtitles, with_timestamps=True, bilingual=bilingual)
        media_type = "text/plain; charset=utf-8"
        filename = f"transcription_{sid}.txt"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache"
        }
    )


# -----------------------------------------------------------------------------
# Endpoints de Telemetría y Observabilidad en Tiempo Real (Objetivo 6)
# -----------------------------------------------------------------------------

@app.get("/api/telemetry")
async def get_telemetry():
    """Devuelve una instantánea del estado de todas las salas."""
    snapshots = await telemetry.get_all_snapshots(manager)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_viewers": manager.get_viewer_count(),
        "sessions": snapshots
    }


@app.get("/api/telemetry/stream")
async def stream_telemetry():
    """
    Transmisión SSE (Server-Sent Events) en vivo para el Dashboard Audiovisual.
    Emite actualizaciones cada 1.5s sin sobrecargar el servidor.
    """
    async def event_generator():
        while True:
            try:
                snapshots = await telemetry.get_all_snapshots(manager)
                data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "total_viewers": manager.get_viewer_count(),
                    "sessions": snapshots
                }
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(1.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en stream SSE: {e}")
                await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# -----------------------------------------------------------------------------
# Endpoint WebSocket Segmentado por Sala (Objetivo 5)
# -----------------------------------------------------------------------------

@app.websocket("/ws/{session_id}")
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: Optional[str] = None,
    pair: Optional[str] = None
):
    """
    Endpoint WebSocket multisesión:
    1. Se suscribe a la sala correspondiente (/ws/{session_id} o /ws?session_id=...).
    2. Envía el historial acumulado de esa sala (desde Valkey o SQLite).
    3. Mantiene el canal abierto para recibir los fragmentos en vivo de esa sala.
    """
    # Determinar el identificador de sala
    query_session = websocket.query_params.get("session_id") or websocket.query_params.get("session")
    active_session = (session_id or query_session or "").lower().strip()

    if not active_session:
        # Si no se especifica sala, buscar si hay alguna sesión registrada o usar default
        try:
            db_sessions = await db.list_sessions()
        except Exception:
            db_sessions = []

        if db_sessions:
            active_session = db_sessions[0]["session_id"].lower().strip()
        elif telemetry._sessions:
            active_session = list(telemetry._sessions.keys())[0]
        else:
            active_session = "default"
            try:
                await db.get_or_create_session(
                    session_id="default",
                    source_lang=None,
                    target_lang=None,
                    title="Sala Principal"
                )
                await telemetry.register_session("default", "Sala Principal", None, None)
            except Exception as e:
                logger.warning(f"No se pudo auto-registrar sala por defecto: {e}")

    await manager.connect(websocket, active_session)

    # 1. Enviar contexto inicial (Historial de la sesión)
    try:
        chronological_history = []
        # Buscar primero en Valkey
        if valkey_client:
            history_key = f"subtitles:{active_session}:history"
            raw_history = await valkey_client.lrange(history_key, 0, 19)

            for item_str in reversed(raw_history):
                try:
                    chronological_history.append(json.loads(item_str))
                except Exception:
                    chronological_history.append({"text_raw": item_str})

        # Si Valkey estaba vacío, recuperar los últimos 20 desde SQLite
        if not chronological_history:
            db_subs = await db.get_subtitles(active_session)
            chronological_history = db_subs[-20:]

        await websocket.send_json({
            "type": "history",
            "session_id": active_session,
            "pair": pair or "all",
            "count": len(chronological_history),
            "data": chronological_history
        })
        logger.info(f"Historial ({len(chronological_history)} items, sala: '{active_session}') enviado a {websocket.client}")
    except Exception as e:
        logger.error(f"Error enviando historial al cliente {websocket.client}: {e}")

    # 2. Mantener socket activo y atender ping/pong
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"Conexión finalizada para {websocket.client}: {e}")
        await manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, timeout_graceful_shutdown=2)

