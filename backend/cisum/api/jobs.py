"""Queue a song for processing: Redis/RQ workers in production, a background thread in dev."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .config import get_settings

log = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None


def enqueue_song(song_id: str) -> None:
    settings = get_settings()
    from ..worker.tasks import process_song

    if settings.queue == "rq":
        from redis import Redis
        from rq import Queue

        Queue("cisum", connection=Redis.from_url(settings.redis_url)).enqueue(
            process_song, song_id, job_timeout=settings.job_timeout_s, job_id=f"song-{song_id}"
        )
    elif settings.queue == "sync":
        process_song(song_id)
    else:
        global _executor
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cisum-job")
        _executor.submit(_run_logged, song_id)


def _run_logged(song_id: str) -> None:
    from ..worker.tasks import process_song

    try:
        process_song(song_id)
    except Exception:  # process_song records failures itself; this is a last resort
        log.exception("job for song %s crashed", song_id)
