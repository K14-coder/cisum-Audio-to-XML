"""Arrangements are generated on demand from the stored analysis and cached in storage.

Keys: songs/{song_id}/analysis.json                         (current, user-editable)
      songs/{song_id}/v{version}/{level}_t{transpose}.{ext}  (cached outputs)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..engine.types import Analysis
from .models import Song
from .storage import Storage

CONTENT_TYPES = {
    "musicxml": "application/vnd.recordare.musicxml+xml",
    "mid": "audio/midi",
    "pdf": "application/pdf",
    "json": "application/json",
}


def analysis_key(song_id: str) -> str:
    return f"songs/{song_id}/analysis.json"


def load_analysis(storage: Storage, song: Song, require_done: bool = True) -> Analysis:
    if (require_done and song.status != "done") or not storage.exists(analysis_key(song.id)):
        raise HTTPException(409, "This song is still being processed.")
    return Analysis.from_dict(json.loads(storage.get_bytes(analysis_key(song.id))))


def save_analysis(storage: Storage, song_id: str, analysis: Analysis) -> None:
    storage.put_bytes(analysis_key(song_id), json.dumps(analysis.to_dict()).encode(), CONTENT_TYPES["json"])


def parse_transpose(value: str | None) -> int | str | None:
    if value is None or value == "":
        return None
    if value == "auto":
        return "auto"
    try:
        t = int(value)
    except ValueError:
        raise HTTPException(422, "transpose must be a whole number of semitones or 'auto'") from None
    if not -6 <= t <= 6:
        raise HTTPException(422, "transpose must be between -6 and 6")
    return t


def _key(song: Song, level: str, transpose: int, ext: str) -> str:
    return f"songs/{song.id}/v{song.analysis_version}/{level}_t{transpose}.{ext}"


def ensure(
    storage: Storage, song: Song, level: str, transpose: int | str | None, require_done: bool = True
) -> tuple[int, dict[str, Any]]:
    """Make sure MusicXML, MIDI and score JSON exist for this level/transposition.
    Returns (resolved transpose, score JSON)."""
    from ..engine.arrange import resolve_transpose
    from ..engine.pipeline import render

    analysis = load_analysis(storage, song, require_done)
    t = resolve_transpose(analysis, level, transpose)
    json_key = _key(song, level, t, "json")
    if storage.exists(json_key) and storage.exists(_key(song, level, t, "musicxml")):
        return t, json.loads(storage.get_bytes(json_key))
    with tempfile.TemporaryDirectory(prefix="cisum-arr-") as tmp:
        paths = render(analysis, level, t, Path(tmp), song.title, ("musicxml", "mid", "json"), artist=song.artist)
        for ext, path in paths.items():
            storage.put_file(_key(song, level, t, ext), path, CONTENT_TYPES[ext])
        return t, json.loads(paths["json"].read_text())


def file_bytes(storage: Storage, song: Song, level: str, transpose: int | str | None, ext: str) -> tuple[bytes, int]:
    if ext not in ("musicxml", "mid", "pdf"):
        raise HTTPException(404, "Unknown file type.")
    t, _ = ensure(storage, song, level, transpose)
    key = _key(song, level, t, ext)
    if ext == "pdf" and not storage.exists(key):
        from ..engine.notate import write_pdf

        with tempfile.TemporaryDirectory(prefix="cisum-pdf-") as tmp:
            xml = Path(tmp) / "score.musicxml"
            xml.write_bytes(storage.get_bytes(_key(song, level, t, "musicxml")))
            pdf = write_pdf(xml, Path(tmp) / "score.pdf")
            storage.put_file(key, pdf, CONTENT_TYPES["pdf"])
    return storage.get_bytes(key), t


def download_name(song: Song, level: str, transpose: int, ext: str) -> str:
    base = "".join(ch if ch.isalnum() or ch in " -_" else "" for ch in song.title).strip() or "arrangement"
    suffix = f" ({level}" + (f", {transpose:+d}" if transpose else "") + ")"
    return f"{base}{suffix}.{ext}"
