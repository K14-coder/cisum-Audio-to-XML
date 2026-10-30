# Cisum

Upload a song recording and get playable piano arrangements back: sheet music at three difficulty levels, MIDI, a letter-name view for beginners, and a falling-notes view, all with playback.

```
upload (rights box ticked)
   │
   ▼
1. INGEST     ffmpeg: decode, check, normalize            → mix.wav + content hash
2. SEPARATE   Demucs (or HPSS fallback)                   → vocals / bass / other
3. ANALYZE    beats · melody · notes · chords · key       → analysis.json   ← computed once per song
4. ARRANGE    rules per difficulty (under a second)       → Easy / Medium / Hard
5. NOTATE     music21 → MusicXML; mido → MIDI; Verovio → PDF
6. VIEW       sheet music · letter names · falling notes · playback · chord editor · share links
```

How each stage works is in [docs/pipeline.md](docs/pipeline.md). The HTTP API is in [docs/api.md](docs/api.md). Rights, takedowns and model licenses are in [docs/legal.md](docs/legal.md).

## What's here

| Folder | What it is |
|---|---|
| `backend/cisum/engine/` | The audio → arrangement engine, usable on its own via the `cisum` command |
| `backend/cisum/api/` | FastAPI app: accounts, uploads with rights consent, songs, arrangements, sharing, reports |
| `backend/cisum/worker/` | Background job that runs the engine (Redis/RQ, or a thread in development) |
| `web/` | React + TypeScript web app (OpenSheetMusicDisplay for notation, Tone.js for playback) |
| `docs/` | Pipeline, API and legal notes |

## Quick start (development)

Requirements: Python 3.11+, Node 20+, ffmpeg, and Cairo (`libcairo2`, for PDF output).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

That's enough to run everything with the DSP fallbacks. For the neural backends (much better results):

```bash
pip install -e ".[ml]"
```

```bash
pip install --no-deps -r requirements-ml.txt
```

Check what's available:

```bash
cisum doctor
```

Build the web app once so the API can serve it:

```bash
cd ../web && npm install && npm run build
```

Run the API, which also serves the web app, processing jobs in a background thread:

```bash
cd ../backend
CISUM_ADMIN_EMAILS=you@example.com uvicorn cisum.api.main:app --reload
```

Open http://localhost:8000 and register. The email in `CISUM_ADMIN_EMAILS` gets the admin report queue. For frontend work, run `npm run dev` in `web/` (port 5173, proxies `/api` to :8000).

### Command line only

```bash
cisum transcribe song.mp3 -o out/ --title "My Song"
cisum arrange out/analysis.json --level hard --transpose 2 -o out/
```

`transcribe` writes `analysis.json` plus `easy|medium|hard` × `.musicxml .mid .json .pdf`. `arrange` re-renders from an analysis without touching the audio, e.g. after editing a chord in the JSON.

## Production (Docker)

```bash
CISUM_ADMIN_EMAILS=you@example.com docker compose up --build
```

This starts the API, a worker, Postgres, Redis and MinIO (S3). Uploads go straight from the browser to MinIO through presigned URLs, and the worker downloads them from there. Model weights are cached in the `models` volume after the first job.

Before going live:
- Put it behind HTTPS and set `CISUM_COOKIE_SECURE=true`.
- Change the MinIO and Postgres passwords in `docker-compose.yml`.
- Set `CISUM_S3_PUBLIC_ENDPOINT_URL` to the address browsers use for the bucket.
- Self-host the piano samples (`VITE_PIANO_SAMPLES_URL`, see `web/README.md`).
- Replace the placeholder takedown email in `web/src/config.ts` and register a DMCA agent (see [docs/legal.md](docs/legal.md)).
- Run several workers to process songs in parallel. Demucs is the slow step on a CPU (roughly a few minutes for a full song); a GPU worker should bring that under a minute (see the comments in `Dockerfile` and `docker-compose.yml`).

## Configuration

All settings are environment variables (or a `.env` file in `backend/`). The full list is in [`backend/cisum/api/config.py`](backend/cisum/api/config.py).

| Variable | Default | Meaning |
|---|---|---|
| `CISUM_DATABASE_URL` | `sqlite:///./data/cisum.db` | Any SQLAlchemy URL; Postgres via `postgresql+psycopg://…` |
| `CISUM_STORAGE` | `local` | `local` (folder `CISUM_STORAGE_DIR`) or `s3` (`CISUM_S3_BUCKET`, `CISUM_S3_ENDPOINT_URL`, …) |
| `CISUM_QUEUE` | `thread` | `rq` (Redis workers via `python -m cisum.worker`), `thread` (in the API process) or `sync` |
| `CISUM_SEPARATOR` / `CISUM_BEATS` / `CISUM_MELODY` / `CISUM_NOTES` | `auto` | Force a backend, e.g. `hpss`, `librosa`, `pyin`, `none` |
| `CISUM_DEVICE` | auto | Torch device for the neural backends (`cpu`, `cuda`) |
| `CISUM_MAX_UPLOAD_MB` / `CISUM_MAX_DURATION_S` | `50` / `600` | Upload limits |
| `CISUM_DELETE_AUDIO_AFTER_PROCESSING` | `true` | Delete the uploaded audio once it's analyzed |
| `CISUM_STRIKE_LIMIT` | `3` | Upheld copyright reports before an account is closed |
| `CISUM_AUTO_HIDE_ON_COPYRIGHT_REPORT` | `true` | Hide a shared arrangement as soon as a copyright report arrives |
| `CISUM_ADMIN_EMAILS` | | Comma-separated emails that become admins when they register |

## Tests

```bash
cd backend
pytest -m "not slow"
```

```bash
pytest
```

The first command runs the fast unit and API tests. The second also runs the full pipeline on a synthetic song with known chords, melody, key and tempo. `tests/synth.py` renders that song; it's an original tune and progression, so it's safe to commit and share. [`scripts/e2e-smoke.cjs`](scripts/e2e-smoke.cjs) drives the whole web flow in a headless browser against a running server.

## Accuracy and limits

- The best results come from songs with a clear lead vocal, a steady beat and pop/rock/folk harmony. Chords are detected from a vocabulary of major, minor, 7th, maj7, m7, sus2, sus4 and dim. Users can fix any chord and every level regenerates.
- Without Demucs, there's no vocal stem. The melody then comes from the top line of the accompaniment, which works for simple mixes and is rough for dense ones.
- The meter is fixed per song (4/4 or 3/4). Songs with mid-song meter changes, heavy rubato, or no clear pitch (rap, spoken word) produce sparse or low-confidence melodies; the app flags these.
