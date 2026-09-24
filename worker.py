#!/usr/bin/env python3
"""
Ingestion Worker (worker.py) - Sprint 2 Evolution
Captura audio en tiempo real, filtra silencios con Silero VAD, transcribe con Groq Whisper
utilizando Domain Biasing (Glosario), traduce con Groq LLaMA (o bypass directo), y publica
en Valkey con aislamiento multisesión (session_id), timestamps relativos y rotación de API keys.
"""

import argparse
import io
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import wave
from collections import deque
from datetime import datetime, timezone
import queue
import threading

# ---------------------------------------------------------------------------
# Carga transparente de PortAudio en Linux
# ---------------------------------------------------------------------------
import ctypes.util
_current_dir = os.path.dirname(os.path.abspath(__file__))
_lib_dir = os.path.join(_current_dir, "lib")
_orig_find_library = ctypes.util.find_library

def _custom_find_library(name: str):
    if name and "portaudio" in name:
        local_path = os.path.join(_lib_dir, "libportaudio.so")
        if os.path.exists(local_path):
            return local_path
    return _orig_find_library(name)

ctypes.util.find_library = _custom_find_library

import numpy as np
import onnxruntime as ort
import redis
import sounddevice as sd
from dotenv import load_dotenv
from groq import Groq, NotFoundError, RateLimitError

# Cargar variables de entorno
load_dotenv()

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WORKER] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("worker")

# Parámetros Base desde .env
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEYS_RAW = os.getenv("GROQ_API_KEYS", "") or GROQ_API_KEY
GROQ_API_KEYS = [k.strip() for k in GROQ_API_KEYS_RAW.split(",") if k.strip()]

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_CHANNEL = os.getenv("VALKEY_CHANNEL", "subtitles:live")
VALKEY_HISTORY_KEY = os.getenv("VALKEY_HISTORY_KEY", "subtitles:history")

CHUNK_SECONDS = float(os.getenv("CHUNK_SECONDS", "3.5"))
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))
VAD_MODEL_PATH = os.getenv("VAD_MODEL_PATH", os.path.join(_current_dir, "silero_vad.onnx"))
SILERO_VAD_URL = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"

GROQ_ASR_MODEL = os.getenv("GROQ_ASR_MODEL", "whisper-large-v3")
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
GROQ_FALLBACK_CHAT_MODEL = os.getenv("GROQ_FALLBACK_CHAT_MODEL", "llama-3.1-8b-instant")

# Matriz Multilingüe y Multisesión
SESSION_ID_DEFAULT = os.getenv("SESSION_ID", "default").lower().strip()
SOURCE_LANG_DEFAULT = os.getenv("SOURCE_LANG", "en").lower().strip()
TARGET_LANG_DEFAULT = os.getenv("TARGET_LANG", "es").lower().strip()

# Glosario & Domain Bias
GLOSSARY_FILE_DEFAULT = os.getenv("GLOSSARY_FILE", "glossary.txt")
GLOSSARY_TERMS_DEFAULT = os.getenv("GLOSSARY_TERMS", "")

# Parámetros de VAD
VAD_WINDOW_SIZE = 512  # 32ms a 16kHz
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
PAUSE_SILENCE_SECONDS = float(os.getenv("PAUSE_SILENCE_SECONDS", "0.6"))
MIN_SPEECH_DURATION = float(os.getenv("MIN_SPEECH_DURATION", "0.8"))

# Mapeo de Idiomas
LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese"
}


class GroqKeyRotator:
    """Gestiona rotación de múltiples API Keys de Groq con cooldown automático ante 429."""

    def __init__(self, api_keys: list[str], start_idx: int = 0):
        self.keys = [k for k in api_keys if k and k != "gsk_tu_api_key_aqui"]
        if not self.keys:
            raise ValueError("No se encontraron API Keys válidas de Groq.")
        self.clients = {k: Groq(api_key=k) for k in self.keys}
        self.cooldowns = {k: 0.0 for k in self.keys}
        self.current_idx = start_idx % len(self.keys)
        self.lock = threading.Lock()
        logger.info(f"GroqKeyRotator inicializado con {len(self.keys)} clave(s) de API (inicio en índice {self.current_idx}).")

    def get_client(self) -> tuple[Groq, str]:
        """Obtiene un cliente activo de Groq cuya clave no esté en enfriamiento."""
        with self.lock:
            now = time.time()
            for _ in range(len(self.keys)):
                key = self.keys[self.current_idx]
                if now >= self.cooldowns[key]:
                    return self.clients[key], key
                self.current_idx = (self.current_idx + 1) % len(self.keys)

            # Si todas están en cooldown, seleccionar la que expire antes
            best_key = min(self.keys, key=lambda k: self.cooldowns[k])
            wait_s = max(0.0, self.cooldowns[best_key] - now)
            if wait_s > 0:
                logger.warning(f"Todas las API Keys en cooldown. Esperando {wait_s:.1f}s...")
                time.sleep(min(wait_s, 2.0))
            return self.clients[best_key], best_key

    def mark_rate_limited(self, key: str, cooldown_s: float = 6.0):
        """Aplica cooldown a una clave tras recibir 429 y conmuta a la siguiente."""
        with self.lock:
            # Si solo hay una clave, el cooldown debe ser corto (3-5s) para liberar el bucket sin congelar la cola
            actual_cooldown = min(cooldown_s, 5.0) if len(self.keys) == 1 else cooldown_s
            self.cooldowns[key] = time.time() + actual_cooldown
            self.current_idx = (self.current_idx + 1) % len(self.keys)
            logger.warning(f"Clave {key[:8]}... en cooldown por {actual_cooldown:.1f}s. Conmutando a siguiente clave.")


def load_glossary(file_path: str = None, env_terms: str = None) -> list[str]:
    """Carga términos técnicos desde archivo local o variable de entorno preservando el orden."""
    terms = []
    seen = set()
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",") if p.strip()]
                    for p in parts:
                        p_lower = p.lower()
                        if p_lower not in seen:
                            seen.add(p_lower)
                            terms.append(p)
            logger.info(f"Glosario cargado desde '{file_path}': {len(terms)} términos.")
        except Exception as e:
            logger.warning(f"Error leyendo glosario '{file_path}': {e}")

    if env_terms:
        parts = [p.strip() for p in env_terms.split(",") if p.strip()]
        for p in parts:
            p_lower = p.lower()
            if p_lower not in seen:
                seen.add(p_lower)
                terms.append(p)

    if not terms:
        default_fallback = [
            "pipeline", "deploy", "commit", "merge", "pull request", "middleware",
            "frontend", "backend", "fullstack", "docker", "kubernetes", "valkey",
            "redis", "websockets", "obs studio", "stream", "latency", "buffer"
        ]
        return default_fallback
    return terms


def ensure_vad_model() -> str:
    """Descarga dinámica del modelo ONNX de Silero VAD si no está presente."""
    if not os.path.exists(VAD_MODEL_PATH):
        logger.info(f"Descargando Silero VAD ONNX desde {SILERO_VAD_URL}...")
        urllib.request.urlretrieve(SILERO_VAD_URL, VAD_MODEL_PATH)
        logger.info(f"Modelo Silero VAD guardado en {VAD_MODEL_PATH}")
    return VAD_MODEL_PATH


class SileroVAD:
    """Clasificador Silero VAD v5 ligero sobre ONNX Runtime con buffer de contexto."""

    def __init__(self, model_path: str):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self.context_size = 64
        self.reset_state()

    def reset_state(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.context_size), dtype=np.float32)
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)

    def is_speech(self, audio_frame: np.ndarray, threshold: float = VAD_THRESHOLD) -> bool:
        if audio_frame.ndim == 1:
            frame = np.expand_dims(audio_frame, axis=0)
        else:
            frame = audio_frame

        x = np.concatenate([self._context, frame.astype(np.float32)], axis=1)
        ort_inputs = {
            "input": x,
            "state": self._state,
            "sr": self._sr
        }
        out, self._state = self.session.run(None, ort_inputs)
        self._context = x[:, -self.context_size:]
        return float(out[0][0]) >= threshold


def float32_to_wav_bytes(audio_data: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convierte array float32 [-1.0, 1.0] a bytes WAV PCM 16-bit en memoria."""
    audio_int16 = (audio_data * 32767.0).clip(-32768, 32767).astype(np.int16)
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return wav_buf.getvalue()


class ValkeyPublisher:
    """Publicador en Valkey con aislamiento multisesión por session_id."""

    def __init__(self, host: str, port: int, session_id: str, source_lang: str, target_lang: str):
        self.host = host
        self.port = port
        self.session_id = session_id.lower().strip()
        self.source_lang = source_lang.lower().strip()
        self.target_lang = target_lang.lower().strip()

        # Tópicos segmentados por sesión (Sprint 2)
        self.channel_session = f"subtitles:{self.session_id}:live"
        self.channel_session_pair = f"subtitles:{self.session_id}:live:{self.source_lang}-{self.target_lang}"
        self.history_key_session = f"subtitles:{self.session_id}:history"

        # Tópicos globales / legacy
        self.channel_global = VALKEY_CHANNEL
        self.history_key_global = VALKEY_HISTORY_KEY

        self.client = None
        self._connect()

    def _connect(self):
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5
            )
            self.client.ping()
            logger.info(f"Conectado a Valkey en {self.host}:{self.port} (Tópico sesión: '{self.channel_session}')")
        except Exception as e:
            logger.warning(f"Conexión con Valkey pendiente ({e}). Se reintentará al publicar.")
            self.client = None

    def publish_subtitle(
        self,
        text_source: str,
        text_target: str,
        seq: int = 1,
        start_time: float = 0.0,
        end_time: float = 0.0,
        metrics: dict = None,
        source_lang: str = None,
        translations: dict = None
    ) -> bool:
        """Publica el subtítulo en los canales de la sesión y en los globales."""
        src = (source_lang or self.source_lang or "en").lower()
        trans = translations or {}
        text_en = trans.get("en", text_source if src == "en" else text_source)
        text_es = trans.get("es", text_target if self.target_lang == "es" else (text_source if src == "es" else text_target))
        text_pt = trans.get("pt", text_target if self.target_lang == "pt" else (text_source if src == "pt" else text_target))

        payload = {
            "session_id": self.session_id,
            "seq": seq,
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "text_source": text_source,
            "text_target": text_target,
            "source_lang": src,
            "target_lang": self.target_lang,
            "translations": {
                "en": text_en,
                "es": text_es,
                "pt": text_pt
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text_en": text_en,
            "text_es": text_es,
            "text_pt": text_pt
        }
        if metrics:
            payload["metrics"] = metrics
        payload_json = json.dumps(payload, ensure_ascii=False)

        for attempt in range(3):
            try:
                if self.client is None:
                    self._connect()
                if self.client is not None:
                    pipe = self.client.pipeline()
                    # 1. Publicar una sola vez al canal canónico de la sesión
                    pipe.publish(self.channel_session, payload_json)
                    pipe.lpush(self.history_key_session, payload_json)
                    pipe.ltrim(self.history_key_session, 0, 49)

                    # 2. Si es la sesión default, actualizar también el historial global
                    if self.session_id == "default":
                        pipe.lpush(self.history_key_global, payload_json)
                        pipe.ltrim(self.history_key_global, 0, 49)

                    pipe.execute()
                    return True
            except (redis.ConnectionError, redis.TimeoutError) as err:
                logger.warning(f"Fallo publicando en Valkey (intento {attempt + 1}/3): {err}")
                self.client = None
                time.sleep(0.5)
            except Exception as ex:
                logger.error(f"Error inesperado en Valkey: {ex}")
                break
        return False


class SubtitlePipeline:
    """Orquesta Whisper ASR (con Biasing) y LLaMA MT con rotación de API Keys y Bypass."""

    def __init__(self, key_rotator: GroqKeyRotator, source_lang: str = "en", target_lang: str = "es", glossary_terms: list[str] = None):
        self.rotator = key_rotator
        self.chat_model = GROQ_CHAT_MODEL
        self._fallback_active = False

        self.source_lang = source_lang
        self.target_lang = target_lang
        self.is_bypass = (self.source_lang == self.target_lang)

        self.glossary_terms = glossary_terms or []
        # Términos core de alta frecuencia que SIEMPRE van en cada prompt
        self.core_terms = self.glossary_terms[:20]
        # Pool rotativo para ciclar los cientos de términos adicionales
        self.rotating_pool = self.glossary_terms[20:]
        self._rot_index = 0
        self.last_transcription = ""

        source_name = LANG_NAMES.get(self.source_lang, self.source_lang.upper())
        target_name = LANG_NAMES.get(self.target_lang, self.target_lang.upper())
        sample_terms = ", ".join(self.glossary_terms[:15]) if self.glossary_terms else "pipeline, deploy, commit, merge, middleware"

        self.system_prompt = (
            f"You are an expert real-time {source_name}-to-{target_name} translator for live subtitles. "
            f"Translate the provided {source_name} text accurately and naturally into {target_name}. "
            f"IMPORTANT: PRESERVE software engineering, DevOps, cloud, and streaming technical terms intact "
            f"in their standard English industry terminology (e.g. {sample_terms}). "
            "Do NOT force unnatural literal translations for common technical jargon. "
            f"Output ONLY the translated {target_name} text without quotes, introductory remarks, notes, or explanations."
        )

    def transcribe(self, wav_bytes: bytes) -> tuple[str, str]:
        """Transcribe audio usando la API Key activa del rotador. Retorna (texto, source_lang_detectado)."""
        fallback_lang = self.source_lang if (self.source_lang and self.source_lang != "auto") else "en"

        # Construir prompt dinámico: Core terms + Muestra rotativa del pool + Contexto previo
        glossary_slice = list(self.core_terms)
        cur_len = sum(len(t) + 2 for t in glossary_slice)
        if self.rotating_pool:
            rot_added = 0
            pool_size = len(self.rotating_pool)
            for i in range(pool_size):
                term = self.rotating_pool[(self._rot_index + i) % pool_size]
                if cur_len + len(term) + 2 <= 580:
                    glossary_slice.append(term)
                    cur_len += len(term) + 2
                    rot_added += 1
                else:
                    break
            self._rot_index = (self._rot_index + rot_added) % pool_size

        asr_prompt = ", ".join(glossary_slice)

        prompt_parts = []
        if asr_prompt:
            prompt_parts.append(asr_prompt)
        if self.last_transcription:
            clean_prev = self.last_transcription.strip()
            if clean_prev:
                prompt_parts.append(f"... {clean_prev[-160:]}")
        dynamic_prompt = ". ".join(prompt_parts)
        if len(dynamic_prompt) > 850:
            dynamic_prompt = dynamic_prompt[:850]

        for _ in range(len(self.rotator.keys)):
            client, active_key = self.rotator.get_client()
            try:
                kwargs = {
                    "file": ("chunk.wav", wav_bytes, "audio/wav"),
                    "model": GROQ_ASR_MODEL,
                    "response_format": "verbose_json"
                }
                if self.source_lang and self.source_lang != "auto":
                    kwargs["language"] = self.source_lang
                if dynamic_prompt:
                    kwargs["prompt"] = dynamic_prompt

                transcription = client.audio.transcriptions.create(**kwargs)
                text = (getattr(transcription, "text", "") or "").strip()
                lang_raw = (getattr(transcription, "language", "") or fallback_lang).lower().strip()
                if lang_raw.startswith("es") or "spanish" in lang_raw:
                    detected_lang = "es"
                elif lang_raw.startswith("pt") or "portuguese" in lang_raw:
                    detected_lang = "pt"
                else:
                    detected_lang = "en"
                return text, detected_lang
            except RateLimitError as e:
                logger.warning(f"RateLimitError (429) en ASR con clave {active_key[:8]}... Conmutando...")
                self.rotator.mark_rate_limited(active_key, cooldown_s=6.0)
                time.sleep(1.0)
                continue
            except Exception as e:
                logger.error(f"Error en Whisper ASR ({active_key[:8]}...): {e}")
                return "", fallback_lang
        return "", fallback_lang

    def translate_all(self, text_source: str, source_lang: str) -> dict[str, str]:
        """
        Traduce el texto a la matriz multilingüe (en, es, pt) usando bypass para el idioma fuente
        y LLaMA para los idiomas restantes con contexto previo y corrección fonética.
        """
        all_langs = ["en", "es", "pt"]
        src = source_lang if source_lang in all_langs else "en"
        translations = {src: text_source}
        targets_needed = [l for l in all_langs if l != src]

        if not targets_needed or not text_source.strip():
            return translations

        target_names = {
            "en": "English",
            "es": "Spanish",
            "pt": "Portuguese"
        }
        needed_desc = ", ".join([f"'{k}' ({target_names[k]})" for k in targets_needed])
        keys_example = ", ".join([f'"{k}": "..."' for k in targets_needed])
        system_prompt = (
            f"You are an expert real-time conference interpreter translating from {target_names.get(src, src)}. "
            f"Translate the current incoming speech accurately, naturally, and concisely into: {needed_desc}. "
            "GUIDELINES:\n"
            "1. If previous context is provided, use it to ensure grammatical coherence, pronoun resolution, and gender agreement.\n"
            "2. If the current text contains an obvious minor phonetic transcription error or cut word from speech recognition, translate the intended meaning rather than literal nonsense.\n"
            "3. Preserve technical, cloud, AI, and industry terms in standard industry terminology.\n"
            "4. Preserve proper names of people, companies, tech brands, and databases (e.g., Dijkstra, Turing, AWS, SQLite, Postgres, OpenAI) intact without translating or altering them.\n"
            f"5. Output MUST be valid JSON with keys: {{{keys_example}}}. Output ONLY valid JSON without markdown fences or explanations."
        )

        user_content = text_source
        if self.last_transcription:
            clean_prev = self.last_transcription.strip()
            if clean_prev:
                user_content = f"[Previous context: {clean_prev[-160:]}]\n[Current speech to translate: {text_source}]"

        models_to_try = [self.chat_model]
        if not self._fallback_active and GROQ_FALLBACK_CHAT_MODEL != self.chat_model:
            models_to_try.append(GROQ_FALLBACK_CHAT_MODEL)

        for model in models_to_try:
            for _ in range(len(self.rotator.keys)):
                client, active_key = self.rotator.get_client()
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        max_tokens=1000
                    )
                    self.chat_model = model
                    content = response.choices[0].message.content.strip()
                    parsed = json.loads(content)
                    for k in targets_needed:
                        if k in parsed and isinstance(parsed[k], str):
                            translations[k] = parsed[k].strip()
                    return translations
                except NotFoundError:
                    logger.warning(f"Modelo '{model}' no accesible. Conmutando a '{GROQ_FALLBACK_CHAT_MODEL}'.")
                    self._fallback_active = True
                    break
                except RateLimitError:
                    logger.warning(f"RateLimitError (429) en Chat con clave {active_key[:8]}... Conmutando...")
                    self.rotator.mark_rate_limited(active_key, cooldown_s=6.0)
                    time.sleep(1.0)
                    continue
                except Exception as e:
                    logger.warning(f"Aviso en traducción multi ({model}): {e}")
                    break

        # Fallback si falló llamada a chat
        for k in targets_needed:
            if k not in translations:
                translations[k] = text_source
        return translations

    def translate(self, text_source: str) -> str:
        """Traduce texto aplicando bypass si los idiomas son idénticos (legacy helper)."""
        if self.is_bypass:
            return text_source

        models_to_try = [self.chat_model]
        if not self._fallback_active and GROQ_FALLBACK_CHAT_MODEL != self.chat_model:
            models_to_try.append(GROQ_FALLBACK_CHAT_MODEL)

        for model in models_to_try:
            for _ in range(len(self.rotator.keys)):
                client, active_key = self.rotator.get_client()
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": text_source}
                        ],
                        temperature=0.0,
                        max_tokens=1000
                    )
                    self.chat_model = model
                    return response.choices[0].message.content.strip()
                except NotFoundError:
                    logger.warning(f"Modelo '{model}' no accesible. Conmutando a '{GROQ_FALLBACK_CHAT_MODEL}'.")
                    self._fallback_active = True
                    break
                except RateLimitError:
                    logger.warning(f"RateLimitError (429) en Chat con clave {active_key[:8]}... Conmutando...")
                    self.rotator.mark_rate_limited(active_key, cooldown_s=60.0)
                    continue
                except Exception as e:
                    logger.error(f"Error en traducción ({model}, clave {active_key[:8]}...): {e}")
                    return ""
        return ""


class AudioWorker:
    """Worker de ingesta multisesión con timestamps acumulativos y observabilidad."""

    def __init__(
        self,
        session_id: str = SESSION_ID_DEFAULT,
        source_lang: str = SOURCE_LANG_DEFAULT,
        target_lang: str = TARGET_LANG_DEFAULT,
        glossary_file: str = GLOSSARY_FILE_DEFAULT
    ):
        self.session_id = session_id.lower().strip()
        self.source_lang = source_lang.lower().strip()
        self.target_lang = target_lang.lower().strip()

        self.session_start_time = time.time()
        last_seq, last_end_time, session_created_ts = self._get_resume_state()
        self.seq_counter = last_seq
        self.start_offset_s = last_end_time
        self.session_created_ts = session_created_ts

        self.glossary_terms = load_glossary(glossary_file, GLOSSARY_TERMS_DEFAULT)
        start_idx = abs(hash(self.session_id)) % max(len(GROQ_API_KEYS), 1)
        self.key_rotator = GroqKeyRotator(GROQ_API_KEYS, start_idx=start_idx)

        vad_path = ensure_vad_model()
        self.vad = SileroVAD(vad_path)
        self.pipeline = SubtitlePipeline(
            key_rotator=self.key_rotator,
            source_lang=self.source_lang,
            target_lang=self.target_lang,
            glossary_terms=self.glossary_terms
        )
        self.publisher = ValkeyPublisher(
            host=VALKEY_HOST,
            port=VALKEY_PORT,
            session_id=self.session_id,
            source_lang=self.source_lang,
            target_lang=self.target_lang
        )

        self.audio_queue = queue.Queue()
        self.inference_queue = queue.Queue(maxsize=50)
        self.running = threading.Event()
        self.running.set()

        self.preroll = deque(maxlen=3)
        self.accumulated_frames = []
        self.in_speech = False
        self.consecutive_silent_frames = 0

        frames_per_sec = SAMPLE_RATE / VAD_WINDOW_SIZE  # 31.25 fps
        self.max_frames = int(CHUNK_SECONDS * frames_per_sec)
        self.min_speech_frames = int(MIN_SPEECH_DURATION * frames_per_sec)
        self.pause_silence_frames = int(PAUSE_SILENCE_SECONDS * frames_per_sec)

        self.request_timestamps = deque()
        self.rpm_lock = threading.Lock()

        self.inference_thread = threading.Thread(target=self._inference_worker_loop, daemon=True)

    def _get_resume_state(self) -> tuple[int, float, float]:
        """Obtiene (ultimo_seq, ultimo_end_time, session_created_ts) desde SQLite para reanudar."""
        try:
            db_path = os.path.join(_current_dir, "subtitles.db")
            if os.path.exists(db_path):
                with sqlite3.connect(db_path, timeout=5.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COALESCE(MAX(seq), 0), COALESCE(MAX(end_time), 0.0) FROM subtitles WHERE session_id = ?",
                        (self.session_id,)
                    )
                    row = cursor.fetchone()
                    seq_val = int(row[0] or 0) if row else 0
                    end_val = float(row[1] or 0.0) if row else 0.0

                    cursor.execute("SELECT created_at FROM sessions WHERE session_id = ?", (self.session_id,))
                    sess_row = cursor.fetchone()
                    created_ts = 0.0
                    if sess_row and sess_row[0]:
                        try:
                            created_ts = datetime.fromisoformat(sess_row[0]).timestamp()
                        except Exception:
                            pass

                    if seq_val > 0:
                        logger.info(f"Reanudando sesión '{self.session_id}' desde seq #{seq_val} y offset base {end_val:.1f}s")
                    return seq_val, end_val, created_ts
        except Exception as e:
            logger.warning(f"Aviso al consultar estado de reanudación: {e}")
        return 0, 0.0, 0.0

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio stream status: {status}")
        self.audio_queue.put(indata[:, 0].copy())

    def _track_request(self) -> int:
        now = time.time()
        with self.rpm_lock:
            self.request_timestamps.append(now)
            while self.request_timestamps and now - self.request_timestamps[0] > 60:
                self.request_timestamps.popleft()
            return len(self.request_timestamps)

    def _inference_worker_loop(self):
        while self.running.is_set():
            try:
                task_item = self.inference_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if isinstance(task_item, tuple):
                    audio_chunk, emit_time = task_item
                else:
                    audio_chunk, emit_time = task_item, time.time()

                start_infer_time = time.time()
                queue_lat_ms = (start_infer_time - emit_time) * 1000
                chunk_duration_s = len(audio_chunk) / SAMPLE_RATE

                # Protección anti-congestión: si el chunk esperó > 8s en cola por rate-limit o red,
                # descartarlo para volver inmediatamente al vivo y evitar latencias de 100.000ms
                if queue_lat_ms > 8000:
                    logger.warning(f"Purgando chunk atrasado ({queue_lat_ms/1000:.1f}s en cola) para recuperar el vivo.")
                    continue

                current_rpm = self._track_request()
                wav_bytes = float32_to_wav_bytes(audio_chunk, SAMPLE_RATE)

                # 1. ASR
                t_asr_start = time.time()
                text_source, detected_lang = self.pipeline.transcribe(wav_bytes)
                asr_lat_ms = (time.time() - t_asr_start) * 1000

                clean_source = text_source.strip()
                hallucinations = {"you", "thank you.", "thank you", "thanks for watching.", "thanks for watching", ".", "..."}
                if not clean_source or len(clean_source) < 2 or clean_source.lower() in hallucinations:
                    continue

                # Actualizar memoria de contexto continuo para el siguiente fragmento
                self.pipeline.last_transcription = clean_source

                # 2. Traducción multilingüe (EN, ES, PT)
                t_trans_start = time.time()
                translations = self.pipeline.translate_all(clean_source, detected_lang)
                trans_lat_ms = (time.time() - t_trans_start) * 1000

                target_lang_choice = self.target_lang if self.target_lang in translations else ("es" if detected_lang != "es" else "en")
                text_target = translations.get(target_lang_choice, clean_source)

                total_perceived_lat_ms = (time.time() - emit_time) * 1000

                if text_target or clean_source:
                    self.seq_counter += 1
                    # Timestamps relativos al inicio de la sesión (acumulativo si se reanudó)
                    rel_end_time = max(0.0, (emit_time - self.session_start_time) + self.start_offset_s)
                    rel_start_time = max(0.0, rel_end_time - chunk_duration_s)

                    metrics_data = {
                        "audio_duration_s": round(chunk_duration_s, 2),
                        "latency_ms": round(total_perceived_lat_ms, 0),
                        "asr_ms": round(asr_lat_ms, 0),
                        "trans_ms": round(trans_lat_ms, 0),
                        "queue_ms": round(queue_lat_ms, 0),
                        "rpm": current_rpm,
                        "bypass": (detected_lang == target_lang_choice)
                    }

                    mode_label = f"Trans: {trans_lat_ms:.0f}ms [det: {detected_lang}]"
                    logger.info(
                        f"[Sesión: '{self.session_id}' #{self.seq_counter} | "
                        f"Rel: {rel_start_time:.1f}s-{rel_end_time:.1f}s | "
                        f"Lat: {total_perceived_lat_ms:.0f}ms | ASR: {asr_lat_ms:.0f}ms | {mode_label} | RPM: {current_rpm}]\n"
                        f"   [{detected_lang.upper()}]: \"{clean_source}\"\n"
                        f"   [{target_lang_choice.upper()}]: \"{text_target}\""
                    )

                    # 3. Publicar con timestamps relativos para persistencia acumulativa y soporte multi-idioma
                    self.publisher.publish_subtitle(
                        text_source=clean_source,
                        text_target=text_target,
                        seq=self.seq_counter,
                        start_time=rel_start_time,
                        end_time=rel_end_time,
                        metrics=metrics_data,
                        source_lang=detected_lang,
                        translations=translations
                    )
            except Exception as e:
                logger.error(f"Error en loop de inferencia: {e}", exc_info=True)
            finally:
                try:
                    self.inference_queue.task_done()
                except ValueError:
                    pass

    def _emit_current_chunk(self):
        if not self.accumulated_frames:
            return

        total_frames = len(self.accumulated_frames)
        if total_frames >= self.min_speech_frames:
            chunk_array = np.concatenate(self.accumulated_frames)
            emit_time = time.time()
            try:
                self.inference_queue.put_nowait((chunk_array, emit_time))
            except queue.Full:
                logger.warning("Cola de inferencia llena, descartando chunk.")

        self.accumulated_frames = []
        self.in_speech = False
        self.consecutive_silent_frames = 0
        self.vad.reset_state()

    def process_frame(self, frame: np.ndarray):
        is_speech = self.vad.is_speech(frame, threshold=VAD_THRESHOLD)

        if is_speech:
            if not self.in_speech:
                self.in_speech = True
                self.accumulated_frames.extend(self.preroll)

            self.accumulated_frames.append(frame)
            self.consecutive_silent_frames = 0

            if len(self.accumulated_frames) >= self.max_frames:
                self._emit_current_chunk()
        else:
            if self.in_speech:
                self.consecutive_silent_frames += 1
                self.accumulated_frames.append(frame)

                if self.consecutive_silent_frames >= self.pause_silence_frames:
                    self._emit_current_chunk()
                elif len(self.accumulated_frames) >= self.max_frames:
                    self._emit_current_chunk()
            else:
                self.preroll.append(frame)

    def run_file(self, wav_file_path: str):
        if not os.path.exists(wav_file_path):
            logger.error(f"Archivo no encontrado: {wav_file_path}")
            return

        logger.info(f"Simulando stream en sesión: '{self.session_id}' desde: {wav_file_path}")
        self.session_start_time = time.time()
        self.inference_thread.start()

        with wave.open(wav_file_path, "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()

            while self.running.is_set():
                raw_bytes = wf.readframes(VAD_WINDOW_SIZE)
                if not raw_bytes:
                    break
                data_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
                if nchannels > 1:
                    data_int16 = data_int16[::nchannels]
                data_float32 = data_int16.astype(np.float32) / 32768.0

                if len(data_float32) == VAD_WINDOW_SIZE:
                    self.process_frame(data_float32)
                time.sleep(VAD_WINDOW_SIZE / SAMPLE_RATE)

        self._emit_current_chunk()
        self.inference_queue.join()
        self.stop()

    def run_stream_url(self, stream_url: str, force_live: bool = False):
        """
        Ingesta continua de audio en tiempo real desde URLs de streaming (YouTube, Twitch, Kick, RTMP, HLS).
        Utiliza yt-dlp para resolver la fuente y FFmpeg para decodificar al vuelo a PCM 16kHz mono.
        """
        logger.info("=" * 68)
        logger.info(f"Ingestion Worker [STREAM ONLINE] - Sesión: '{self.session_id}'")
        logger.info(f"   URL del Stream:   {stream_url}")
        logger.info(f"   Par de Idiomas:   [{self.source_lang.upper()} -> {self.target_lang.upper()}]")
        logger.info(f"   Bypass LLM:       {'SÍ (Nativo)' if self.pipeline.is_bypass else 'NO (IA Groq)'}")
        logger.info(f"   API Keys Groq:    {len(self.key_rotator.keys)} activa(s)")
        logger.info(f"   Tópico Valkey:    {self.publisher.channel_session}")
        logger.info("=" * 68)

        self.session_start_time = time.time()
        self.inference_thread.start()

        # Determinar ejecutable de FFmpeg
        import shutil
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            try:
                import static_ffmpeg
                static_ffmpeg.add_paths()
                ffmpeg_exe = shutil.which("ffmpeg")
            except Exception:
                pass
        if not ffmpeg_exe:
            try:
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_exe = "ffmpeg"

        target_url = stream_url
        is_live = False
        user_agent = None

        # Detección de protocolos directos de livestream
        if any(stream_url.lower().startswith(p) for p in ("rtmp://", "rtsp://")) or force_live:
            is_live = True

        # Si es enlace web de plataforma (YouTube, Twitch, Kick, etc.)
        is_direct = any(stream_url.lower().startswith(p) for p in ("rtmp://", "rtsp://")) or stream_url.lower().endswith((".mp3", ".wav", ".aac"))
        if not is_direct:
            try:
                import yt_dlp
                logger.info("Extrayendo flujo de audio con yt-dlp...")
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'socket_timeout': 15,
                    'noplaylist': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(stream_url, download=False)
                    if info:
                        if 'entries' in info and info['entries']:
                            info = info['entries'][0]
                        target_url = info.get('url') or stream_url
                        # Un stream está actualmente en vivo si is_live es True o live_status es 'is_live'
                        # NOTA: 'was_live' indica un VOD de un stream terminado, NO un stream en vivo actual
                        is_currently_live = bool(info.get('is_live')) or (info.get('live_status') == 'is_live')
                        if is_currently_live or force_live:
                            is_live = True
                        user_agent = info.get('http_headers', {}).get('User-Agent')
                        title = info.get('title')
                        duration = info.get('duration')
                        dur_str = f" ({duration}s)" if duration else ""
                        logger.info(f"Fuente detectada: '{title or stream_url}' (En vivo: {is_live}{dur_str})")
            except Exception as e:
                logger.warning(f"yt-dlp aviso: {e}. Conectando directamente con FFmpeg...")
                target_url = stream_url

        # Configurar FFmpeg
        cmd = [ffmpeg_exe]

        if is_live:
            # -------------------------------------------------------------
            # LIVESTREAM EN VIVO (YouTube Live, Twitch, Kick, RTMP, HLS):
            # No buscar posición previa con -ss ni limitar con -re.
            # Sintonizar de inmediato al MOMENTO ACTUAL / REAL en donde va el stream (live edge).
            # -------------------------------------------------------------
            logger.info("Modo LIVESTREAM activo: sintonizando directamente al momento real del stream (live edge, sin -ss).")
            if self.session_created_ts > 0:
                real_elapsed = max(0.0, time.time() - self.session_created_ts)
                self.start_offset_s = max(self.start_offset_s, real_elapsed)
                logger.info(f"Offset temporal de livestream sincronizado con tiempo real: {self.start_offset_s:.1f}s")

            cmd.extend([
                "-fflags", "+nobuffer+flush_packets",
                "-flags", "low_delay",
                "-live_start_index", "-1"
            ])
        else:
            # -------------------------------------------------------------
            # VIDEO GRABADO / VOD (YouTube video o archivo con duración):
            # Continuar exactamente en el segundo donde fue pausado.
            # -------------------------------------------------------------
            if self.start_offset_s > 0:
                cmd.extend(["-ss", str(round(self.start_offset_s, 2))])
                logger.info(f"Modo VOD: reanudando decodificación desde offset temporal previo: {self.start_offset_s:.1f}s")

            # Decodificar a velocidad real 1.0x estricta
            cmd.append("-re")

        # Opciones de reconexión y agente para URLs remotas
        if target_url.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
            ])
            if user_agent:
                cmd.extend(["-user_agent", user_agent])

        cmd.extend([
            "-loglevel", "warning",
            "-i", target_url,
            "-vn",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "pipe:1"
        ])

        logger.info(f"Iniciando decodificación continua con FFmpeg ({'tiempo real 1x' if not is_live else 'en vivo'})...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**6
        )

        bytes_per_frame = VAD_WINDOW_SIZE * 2  # 512 muestras * 2 bytes = 1024 bytes
        frame_count = 0
        start_decode_time = time.time()

        try:
            while self.running.is_set():
                raw_bytes = proc.stdout.read(bytes_per_frame)
                if not raw_bytes or len(raw_bytes) < bytes_per_frame:
                    if proc.poll() is not None:
                        exit_code = proc.poll()
                        if exit_code != 0:
                            err_msg = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                            logger.warning(f"FFmpeg finalizó con código {exit_code}: {err_msg.strip()[-300:]}")
                        else:
                            logger.info("Flujo del stream o video finalizado normalmente.")
                        break
                    time.sleep(0.01)
                    continue

                frame_count += 1
                if not is_live:
                    # Garantizar ritmo de reproducción en tiempo real 1.0x estricto
                    target_wall_time = start_decode_time + (frame_count * (VAD_WINDOW_SIZE / SAMPLE_RATE))
                    delay = target_wall_time - time.time()
                    if delay > 0:
                        time.sleep(delay)

                data_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
                data_float32 = data_int16.astype(np.float32) / 32768.0
                self.process_frame(data_float32)

        except KeyboardInterrupt:
            logger.info("Detención manual solicitada por el usuario.")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._emit_current_chunk()
            self.inference_queue.join()
            self.stop()

    def run(self, input_device=None):
        self.session_start_time = time.time()
        self.inference_thread.start()
        logger.info("=" * 68)
        logger.info(f"Ingestion Worker Iniciado - Sesión: '{self.session_id}' (Sprint 2)")
        logger.info(f"   Par de Idiomas:   [{self.source_lang.upper()} -> {self.target_lang.upper()}]")
        logger.info(f"   Bypass LLM:       {'SÍ (Nativo)' if self.pipeline.is_bypass else 'NO (IA Groq)'}")
        logger.info(f"   API Keys Groq:    {len(self.key_rotator.keys)} activa(s) con rotación automática")
        logger.info(f"   Glosario Activo:  {len(self.glossary_terms)} términos cargados")
        logger.info(f"   Tópico Valkey:    {self.publisher.channel_session}")
        logger.info("   Escuchando audio... (Ctrl+C para detener)")
        logger.info("=" * 68)

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=VAD_WINDOW_SIZE,
                device=input_device,
                callback=self._audio_callback
            )
        except Exception as e:
            logger.error(f"Fallo al abrir dispositivo de audio: {e}")
            return

        leftover = np.empty(0, dtype=np.float32)

        try:
            with stream:
                while self.running.is_set():
                    try:
                        raw_data = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    leftover = np.concatenate((leftover, raw_data))
                    while len(leftover) >= VAD_WINDOW_SIZE:
                        frame = leftover[:VAD_WINDOW_SIZE]
                        leftover = leftover[VAD_WINDOW_SIZE:]
                        self.process_frame(frame)
        except KeyboardInterrupt:
            logger.info("\nDetención solicitada por usuario (Ctrl+C).")
        finally:
            self.stop()

    def stop(self):
        self.running.clear()
        if self.inference_thread.is_alive():
            self.inference_thread.join(timeout=2.0)
        logger.info(f"Worker de sesión '{self.session_id}' detenido limpiamente.")


def list_audio_devices():
    print("\n--- Dispositivos de Entrada de Audio ---")
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            print(f"[{idx}] {dev['name']} (Canales in: {dev['max_input_channels']}, SR: {dev['default_samplerate']}Hz)")
    print("----------------------------------------\n")


def validate_environment():
    if not GROQ_API_KEYS:
        logger.error(
            "\n" + "=" * 65 + "\n"
            "ERROR DE CONFIGURACIÓN: 'GROQ_API_KEY' o 'GROQ_API_KEYS' no configurada.\n"
            "   Por favor añade tu clave de Groq en .env.\n" +
            "=" * 65
        )
        sys.exit(1)


def main():
    validate_environment()

    parser = argparse.ArgumentParser(description="Live Audio Ingestion Worker (Sprint 2)")
    parser.add_argument("--session-id", type=str, default=SESSION_ID_DEFAULT, help="Identificador único de sala/sesión (ej. stage-a)")
    parser.add_argument("--source-lang", type=str, default=SOURCE_LANG_DEFAULT, help="Idioma de origen (ej. en, es)")
    parser.add_argument("--target-lang", type=str, default=TARGET_LANG_DEFAULT, help="Idioma de destino (ej. es, en, pt)")
    parser.add_argument("--glossary", type=str, default=GLOSSARY_FILE_DEFAULT, help="Ruta al archivo de glosario")
    parser.add_argument("--device", type=int, default=None, help="Índice del micrófono de entrada")
    parser.add_argument("--list-devices", action="store_true", help="Listar dispositivos de audio y salir")
    parser.add_argument("--file", type=str, default=None, help="Simular ingesta desde archivo WAV")
    parser.add_argument("--stream-url", type=str, default=None, help="URL de stream en vivo (YouTube, Twitch, Kick, RTMP, HLS)")
    parser.add_argument("--is-live", action="store_true", help="Forzar modo livestream (sintoniza al live-edge sin fast-seek a posición previa)")
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    worker = AudioWorker(
        session_id=args.session_id,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        glossary_file=args.glossary
    )
    if args.stream_url:
        worker.run_stream_url(args.stream_url, force_live=args.is_live)
    elif args.file:
        worker.run_file(args.file)
    else:
        worker.run(input_device=args.device)


if __name__ == "__main__":
    main()
