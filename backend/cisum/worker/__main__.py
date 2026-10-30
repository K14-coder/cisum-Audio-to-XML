"""Run a job worker: `python -m cisum.worker` (needs CISUM_QUEUE=rq and Redis)."""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from ..api.config import get_settings
from ..api.db import init_db


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_db()
    # Load the models once per worker process instead of once per job.
    from ..engine import transcribe

    transcribe.available()
    conn = Redis.from_url(settings.redis_url)
    Worker([Queue("cisum", connection=conn)], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
