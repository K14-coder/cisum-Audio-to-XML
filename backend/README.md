# Cisum backend

Python package `cisum`:

- `cisum.engine`: the audio → piano arrangement engine (ingest, separate, analyze, arrange, notate). Use it from the `cisum` command or call `cisum.engine.pipeline.run` directly.
- `cisum.api`: the FastAPI app (`uvicorn cisum.api.main:app`).
- `cisum.worker`: the processing job, plus an RQ worker (`python -m cisum.worker`).

Setup, configuration and deployment are in the [main README](../README.md). How the engine works is in [docs/pipeline.md](../docs/pipeline.md).

```bash
pip install -e ".[dev]"
```

```bash
pip install -e ".[ml]" && pip install --no-deps -r requirements-ml.txt
```

```bash
cisum doctor
```

```bash
pytest -m "not slow"
```

Run the first command for the base install with the DSP fallbacks, and the second for the neural backends. `cisum doctor` shows which backends load, and the last command runs the fast tests (drop `-m "not slow"` to include the full pipeline runs).

To render the synthetic test song to listen to or feed to the CLI:

```bash
python -m tests.synth out/song
```

```bash
cisum transcribe out/song/mix.wav -o out/arr --stems out/song/stems
```
