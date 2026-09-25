"""
Módulo de Base de Datos y Persistencia SQLite (database.py) - Sprint 2
Gestiona la persistencia acumulativa de sesiones de subtitulado,
rangos temporales relativos (start_time / end_time) y exportación de archivos.
"""

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("DB_PATH", os.path.join(REPO_ROOT, "subtitles.db"))


def init_db(db_path: str = DB_PATH):
    """Inicializa el esquema de base de datos SQLite con índices de alto rendimiento."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")

            # Tabla de Sesiones
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                source_lang TEXT DEFAULT 'en',
                target_lang TEXT DEFAULT 'es',
                stream_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            );
            """)

            # Migración: agregar stream_url si no existe en tablas existentes
            cursor.execute("PRAGMA table_info(sessions);")
            columns = [col[1] for col in cursor.fetchall()]
            if "stream_url" not in columns:
                cursor.execute("ALTER TABLE sessions ADD COLUMN stream_url TEXT;")

            # Tabla de Subtítulos con Timestamps Relativos
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subtitles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                text_source TEXT NOT NULL,
                text_target TEXT NOT NULL,
                source_lang TEXT,
                target_lang TEXT,
                created_at TEXT NOT NULL,
                latency_ms REAL,
                asr_ms REAL,
                trans_ms REAL,
                translations TEXT,
                text_pt TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """)

            # Migración: agregar translations y text_pt si no existen
            cursor.execute("PRAGMA table_info(subtitles);")
            sub_cols = [col[1] for col in cursor.fetchall()]
            if "translations" not in sub_cols:
                cursor.execute("ALTER TABLE subtitles ADD COLUMN translations TEXT;")
            if "text_pt" not in sub_cols:
                cursor.execute("ALTER TABLE subtitles ADD COLUMN text_pt TEXT;")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_session ON subtitles(session_id, seq);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);")
    finally:
        conn.close()


class DatabaseManager:
    """Gestor asíncrono sobre SQLite para FastAPI y Workers."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        init_db(self.db_path)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    async def get_or_create_session(
        self,
        session_id: str,
        source_lang: str = "en",
        target_lang: str = "es",
        title: str = None,
        stream_url: str = None
    ) -> Dict[str, Any]:
        """Crea o recupera una sesión activa con URL de stream opcional."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                now = datetime.now(timezone.utc).isoformat()
                if row:
                    if stream_url:
                        cursor.execute(
                            "UPDATE sessions SET updated_at = ?, status = 'active', stream_url = ? WHERE session_id = ?",
                            (now, stream_url, session_id)
                        )
                    else:
                        cursor.execute(
                            "UPDATE sessions SET updated_at = ?, status = 'active' WHERE session_id = ?",
                            (now, session_id)
                        )
                    return dict(row)
                else:
                    session_title = title or f"Sesión {session_id.capitalize()}"
                    cursor.execute("""
                    INSERT INTO sessions (session_id, title, source_lang, target_lang, stream_url, created_at, updated_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                    """, (session_id, session_title, source_lang, target_lang, stream_url, now, now))
                    return {
                        "session_id": session_id,
                        "title": session_title,
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "stream_url": stream_url,
                        "created_at": now,
                        "updated_at": now,
                        "status": "active"
                    }
        return await asyncio.to_thread(_sync_op)

    async def add_subtitle(
        self,
        session_id: str,
        seq: int,
        start_time: float,
        end_time: float,
        text_source: str,
        text_target: str,
        source_lang: str = "en",
        target_lang: str = "es",
        latency_ms: float = 0.0,
        asr_ms: float = 0.0,
        trans_ms: float = 0.0,
        translations: Optional[Dict[str, str]] = None,
        text_pt: Optional[str] = None
    ) -> int:
        """Almacena un subtítulo de forma acumulativa en la base de datos."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now(timezone.utc).isoformat()
                # Asegurar que la sesión exista
                cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
                if not cursor.fetchone():
                    cursor.execute("""
                    INSERT INTO sessions (session_id, title, source_lang, target_lang, created_at, updated_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'active')
                    """, (session_id, f"Sesión {session_id}", source_lang, target_lang, now, now))

                translations_json = json.dumps(translations, ensure_ascii=False) if translations else None
                pt_val = text_pt or (translations.get("pt") if isinstance(translations, dict) else None)

                cursor.execute("""
                INSERT INTO subtitles (
                    session_id, seq, start_time, end_time, text_source, text_target,
                    source_lang, target_lang, created_at, latency_ms, asr_ms, trans_ms,
                    translations, text_pt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, seq, start_time, end_time, text_source, text_target,
                    source_lang, target_lang, now, latency_ms, asr_ms, trans_ms,
                    translations_json, pt_val
                ))
                if source_lang and source_lang != "auto":
                    cursor.execute("""
                    UPDATE sessions 
                    SET source_lang = ?, updated_at = ? 
                    WHERE session_id = ? AND (source_lang IS NULL OR source_lang = 'auto')
                    """, (source_lang, now, session_id))
                else:
                    cursor.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()
                return cursor.lastrowid
        return await asyncio.to_thread(_sync_op)

    async def get_subtitles(self, session_id: str) -> List[Dict[str, Any]]:
        """Obtiene la lista cronológica completa de subtítulos de una sesión."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                SELECT seq, start_time, end_time, text_source, text_target, source_lang, target_lang,
                       created_at, latency_ms, asr_ms, trans_ms, translations, text_pt
                FROM subtitles
                WHERE session_id = ?
                ORDER BY seq ASC, start_time ASC
                """, (session_id,))
                rows = []
                for row in cursor.fetchall():
                    item = dict(row)
                    if item.get("translations"):
                        try:
                            item["translations"] = json.loads(item["translations"])
                        except Exception:
                            item["translations"] = {}
                    else:
                        item["translations"] = {}
                    if not item.get("text_pt") and item["translations"].get("pt"):
                        item["text_pt"] = item["translations"]["pt"]
                    rows.append(item)
                return rows
        return await asyncio.to_thread(_sync_op)

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """Lista todas las sesiones registradas con conteo de fragmentos y métricas acumuladas."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                SELECT s.session_id, s.title, s.source_lang, s.target_lang, s.stream_url, s.created_at, s.updated_at, s.status,
                       COUNT(sub.id) as total_subtitles,
                       MAX(sub.end_time) as duration_seconds,
                       AVG(sub.latency_ms) as avg_latency_ms
                FROM sessions s
                LEFT JOIN subtitles sub ON s.session_id = sub.session_id
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                """)
                return [dict(row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_sync_op)

    async def close_session(self, session_id: str) -> bool:
        """Marca una sesión como finalizada/cerrada (Inactiva)."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute("UPDATE sessions SET status = 'closed', updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_sync_op)

    async def resume_session(self, session_id: str) -> bool:
        """Reactiva una sesión pasando su estado a 'active'."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute("UPDATE sessions SET status = 'active', updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_sync_op)

    async def delete_session(self, session_id: str) -> bool:
        """Elimina permanentemente una sesión y todos sus subtítulos asociados."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM subtitles WHERE session_id = ?", (session_id,))
                cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_sync_op)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene una sesión específica por su ID si existe."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_sync_op)

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        stream_url: Optional[str] = None,
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Actualiza los campos editables de una sesión (título, stream_url, idioma de origen y destino)."""
        def _sync_op():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                existing = dict(row)
                new_title = title.strip() if title is not None else existing.get("title")
                new_stream_url = stream_url.strip() if stream_url is not None else existing.get("stream_url")
                new_source_lang = source_lang.strip() if source_lang is not None else existing.get("source_lang")
                new_target_lang = target_lang.strip() if target_lang is not None else existing.get("target_lang")
                now = datetime.now(timezone.utc).isoformat()

                cursor.execute("""
                    UPDATE sessions
                    SET title = ?, stream_url = ?, source_lang = ?, target_lang = ?, updated_at = ?
                    WHERE session_id = ?
                """, (new_title, new_stream_url, new_source_lang, new_target_lang, now, session_id))
                conn.commit()

                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                updated_row = cursor.fetchone()
                return dict(updated_row) if updated_row else None
        return await asyncio.to_thread(_sync_op)



# Instancia singleton global
db = DatabaseManager()
