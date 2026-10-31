import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A fresh app with its own SQLite file and storage folder, running jobs inline.
    The audio analysis is replaced by a canned song model so tests stay fast."""
    monkeypatch.setenv("CISUM_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("CISUM_STORAGE", "local")
    monkeypatch.setenv("CISUM_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("CISUM_QUEUE", "sync")
    monkeypatch.setenv("CISUM_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("CISUM_WEB_DIST", str(tmp_path / "no-web"))

    from cisum.api import config, db, storage

    config.get_settings.cache_clear()
    db.reset_engine()
    storage.reset_storage()

    from fastapi.testclient import TestClient

    from cisum.api.main import create_app
    from cisum.worker import tasks

    from .test_engine_units import _analysis

    calls = []

    def fake_run_analysis(path, progress):
        calls.append(path)
        progress("separating", 0.2, "Separating instruments…")
        progress("analyzing", 0.6, "Analyzing beats, melody, chords and key…")
        return _analysis()

    monkeypatch.setattr(tasks, "run_analysis", fake_run_analysis)
    with TestClient(create_app()) as client:
        client.analysis_calls = calls
        yield client
    db.reset_engine()
    storage.reset_storage()
    config.get_settings.cache_clear()
