"""
Módulo de Formateo y Exportación de Transcripciones (exporters.py) - Sprint 2
Genera archivos en formato estándar SRT, WebVTT (VTT) y TXT limpio o con marcas horarias.
"""

from typing import List, Dict, Any


def seconds_to_srt_time(seconds: float) -> str:
    """Convierte segundos float a formato de tiempo SRT (HH:MM:SS,mmm)."""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    if msecs >= 1000:
        msecs = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"


def seconds_to_vtt_time(seconds: float) -> str:
    """Convierte segundos float a formato de tiempo WebVTT (HH:MM:SS.mmm)."""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    if msecs >= 1000:
        msecs = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{msecs:03d}"


def seconds_to_simple_time(seconds: float) -> str:
    """Convierte segundos a formato simple de lectura para TXT [HH:MM:SS]."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"[{hrs:02d}:{mins:02d}:{secs:02d}]"


def generate_srt(subtitles: List[Dict[str, Any]], bilingual: bool = False, prefer_source: bool = False) -> str:
    """
    Genera contenido en formato SubRip (.srt) estándar:
    1
    00:00:01,230 --> 00:00:04,560
    Texto en español
    Texto en inglés (opcional si bilingual=True)
    """
    blocks = []
    for idx, sub in enumerate(subtitles, start=1):
        start_ts = seconds_to_srt_time(sub["start_time"])
        end_ts = seconds_to_srt_time(sub["end_time"])

        target_text = sub.get("text_target") or sub.get("text_es") or ""
        source_text = sub.get("text_source") or sub.get("text_en") or ""

        if bilingual and source_text and source_text != target_text:
            text_block = f"{target_text}\n{source_text}"
        elif prefer_source and source_text:
            text_block = source_text
        else:
            text_block = target_text or source_text

        blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text_block}\n")
    return "\n".join(blocks)


def generate_vtt(subtitles: List[Dict[str, Any]], bilingual: bool = False, prefer_source: bool = False) -> str:
    """Genera contenido en formato WebVTT (.vtt) con cabecera estándar."""
    lines = ["WEBVTT", "Kind: captions", ""]
    for idx, sub in enumerate(subtitles, start=1):
        start_ts = seconds_to_vtt_time(sub["start_time"])
        end_ts = seconds_to_vtt_time(sub["end_time"])

        target_text = sub.get("text_target") or sub.get("text_es") or ""
        source_text = sub.get("text_source") or sub.get("text_en") or ""

        if bilingual and source_text and source_text != target_text:
            text_block = f"{target_text}\n{source_text}"
        elif prefer_source and source_text:
            text_block = source_text
        else:
            text_block = target_text or source_text

        lines.append(f"{idx}")
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(text_block)
        lines.append("")
    return "\n".join(lines)


def generate_txt(subtitles: List[Dict[str, Any]], with_timestamps: bool = True, bilingual: bool = False) -> str:
    """Genera transcripción en texto plano (.txt) continuo o con marcas de tiempo."""
    lines = []
    for sub in subtitles:
        target_text = sub.get("text_target") or sub.get("text_es") or ""
        source_text = sub.get("text_source") or sub.get("text_en") or ""

        if bilingual and source_text and source_text != target_text:
            text = f"{target_text} ({source_text})"
        else:
            text = target_text or source_text

        if with_timestamps:
            ts = seconds_to_simple_time(sub["start_time"])
            lines.append(f"{ts} {text}")
        else:
            lines.append(text)
    return "\n".join(lines)
