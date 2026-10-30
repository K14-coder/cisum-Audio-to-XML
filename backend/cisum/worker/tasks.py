"""The background job: download the upload, run the engine, store the analysis, and
pre-render the default arrangements."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

from ..api.arrangements import ensure, save_analysis
from ..api.config import get_settings
from ..api.db import session_scope
from ..api.models import Song, Upload, now
from ..api.storage import get_storage
from ..engine.audio import AudioError, sha256_file
from ..engine.types import LEVELS, Analysis

log = logging.getLogger(__name__)


def _cache_key(audio_hash: str) -> str:
    from ..engine.pipeline import PIPELINE_VERSION

    return f"audio/{audio_hash}/v{PIPELINE_VERSION}/analysis.json"


def run_analysis(audio_path: Path, progress) -> Analysis:
    """Run stages 1-3 of the engine. Separate function so tests can swap it out."""
    from ..engine.analyze import AnalyzeOptions
    from ..engine.pipeline import PipelineOptions, run

    s = get_settings()
    options = PipelineOptions(
        levels=(),
        separator=s.separator,
        demucs_model=s.demucs_model,
        analyze=AnalyzeOptions(beats=s.beats, melody=s.melody, notes=s.notes, device=s.device),
        max_duration_s=s.max_duration_s,
    )
    with tempfile.TemporaryDirectory(prefix="cisum-out-") as out:
        return run(audio_path, Path(out), options, progress).analysis


class _Reporter:
    """Writes progress to the song row, at most a few times a second."""

    def __init__(self, song_id: str):
        self.song_id = song_id
        self.last = (None, -1.0, None)
        self.last_time = 0.0

    def __call__(self, status: str, progress: float, message: str) -> None:
        if status == "done":
            return  # the job sets "done" itself once everything is stored
        changed_stage = status != self.last[0] or message != self.last[2]
        if not changed_stage and (progress - self.last[1] < 0.01 or time.time() - self.last_time < 0.3):
            return
        self.last, self.last_time = (status, progress, message), time.time()
        with session_scope() as db:
            song = db.get(Song, self.song_id)
            if song is not None:
                song.status, song.progress, song.stage_message = status, progress, message


def process_song(song_id: str) -> None:
    storage = get_storage()
    settings = get_settings()
    report = _Reporter(song_id)
    with session_scope() as db:
        song = db.get(Song, song_id)
        if song is None or song.deleted_at is not None:
            return
        upload = db.get(Upload, song.upload_id)
        upload_id, storage_key, filename = upload.id, upload.storage_key, upload.filename

    report("ingesting", 0.01, "Preparing audio…")
    try:
        with tempfile.TemporaryDirectory(prefix="cisum-job-") as tmp:
            src = Path(tmp) / ("input" + (Path(filename).suffix.lower()[:8] or ".audio"))
            storage.download(storage_key, src)
            audio_hash = sha256_file(src)
            cache = _cache_key(audio_hash)
            if storage.exists(cache):
                report("analyzing", 0.8, "Found an earlier analysis of this recording…")
                analysis = Analysis.from_dict(json.loads(storage.get_bytes(cache)))
            else:
                analysis = run_analysis(src, report)
                storage.put_bytes(cache, json.dumps(analysis.to_dict()).encode(), "application/json")
        analysis.version = 1
        save_analysis(storage, song_id, analysis)

        with session_scope() as db:
            song = db.get(Song, song_id)
            song.audio_hash = audio_hash
            song.duration_s = analysis.duration_s
            song.analysis_version = 1
            song.backends = analysis.backends
            for i, level in enumerate(LEVELS):
                report("arranging", 0.9 + 0.1 * i / len(LEVELS), f"Writing the {level} arrangement…")
                ensure(storage, song, level, None, require_done=False)
            song.status, song.progress, song.stage_message = "done", 1.0, "Ready"
            song.error_code = song.error_message = None
    except AudioError as e:
        _fail(song_id, e.code, e.message)
    except Exception:
        log.exception("processing song %s failed", song_id)
        _fail(song_id, "internal", "Something went wrong while processing this song. Please try again later.")
    finally:
        if settings.delete_audio_after_processing:
            try:
                storage.delete(storage_key)
                with session_scope() as db:
                    db.get(Upload, upload_id).audio_deleted_at = now()
            except Exception:
                log.exception("couldn't delete audio for song %s", song_id)


def _fail(song_id: str, code: str, message: str) -> None:
    with session_scope() as db:
        song = db.get(Song, song_id)
        if song is not None:
            song.status, song.stage_message = "failed", message
            song.error_code, song.error_message = code, message

