"""HTTP API: accounts, uploads with rights consent, processing, editing, sharing, reports."""

import json

import pytest

CSRF = {"X-Cisum-CSRF": "1"}
AUDIO = b"RIFF....WAVEfmt fake audio bytes for the canned analysis"


def register(client, email="user@example.com", password="correct horse"):
    r = client.post("/api/auth/register", json={"email": email, "password": password}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()


def notice_version(client):
    return client.get("/api/legal/rights-notice").json()["version"]


def upload_song(client, title="My Song", data=AUDIO, filename="song.wav"):
    ticket = client.post(
        "/api/uploads",
        json={
            "filename": filename,
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "rights_confirmed": True,
            "rights_notice_version": notice_version(client),
        },
        headers=CSRF,
    )
    assert ticket.status_code == 201, ticket.text
    t = ticket.json()
    assert t["upload"]["url"].startswith("/api/uploads/")
    r = client.put(t["upload"]["url"], content=data, headers={**t["upload"]["headers"], **CSRF})
    assert r.status_code == 204, r.text
    r = client.post(f"/api/uploads/{t['upload_id']}/complete", json={"title": title, "artist": "Me"}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- accounts

def test_register_login_logout(api):
    body = register(api)
    assert body["user"]["email"] == "user@example.com" and body["token"]
    assert api.get("/api/auth/me").json()["email"] == "user@example.com"
    assert api.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert api.get("/api/auth/me").status_code == 401
    assert api.post("/api/auth/login", json={"email": "user@example.com", "password": "wrong pass"}).status_code == 401
    r = api.post("/api/auth/login", json={"email": "USER@example.com", "password": "correct horse"})
    assert r.status_code == 200
    # Bearer tokens work without the cookie.
    api.cookies.clear()
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200


def test_duplicate_email_and_validation(api):
    register(api)
    api.cookies.clear()
    assert api.post("/api/auth/register", json={"email": "user@example.com", "password": "another one"}).status_code == 409
    assert api.post("/api/auth/register", json={"email": "nope", "password": "longenough"}).status_code == 422
    assert api.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422


def test_cookie_writes_need_csrf_header(api):
    register(api)
    r = api.post("/api/uploads", json={})
    assert r.status_code == 403 and r.json()["detail"] == "missing CSRF header"


# ---------------------------------------------------------------- uploads and consent

def test_upload_requires_current_rights_consent(api):
    register(api)
    base = {"filename": "a.mp3", "content_type": "audio/mpeg", "size_bytes": 10}
    v = notice_version(api)
    r = api.post("/api/uploads", json={**base, "rights_confirmed": False, "rights_notice_version": v}, headers=CSRF)
    assert r.status_code == 422 and "rights" in r.json()["detail"]
    r = api.post("/api/uploads", json={**base, "rights_confirmed": True, "rights_notice_version": "2001-01-01"}, headers=CSRF)
    assert r.status_code == 422 and "notice" in r.json()["detail"]
    r = api.post("/api/uploads", json={**base, "content_type": "text/plain", "rights_confirmed": True, "rights_notice_version": v}, headers=CSRF)
    assert r.status_code == 422
    r = api.post("/api/uploads", json={**base, "size_bytes": 10**10, "rights_confirmed": True, "rights_notice_version": v}, headers=CSRF)
    assert r.status_code == 413


def test_full_flow_and_consent_record(api):
    register(api)
    song = upload_song(api)
    assert song["title"] == "My Song"
    # The sync queue already ran the job.
    song = api.get(f"/api/songs/{song['id']}").json()
    assert song["status"] == "done" and song["progress"] == 1.0 and song["analysis_version"] == 1
    assert [s["id"] for s in api.get("/api/songs").json()["songs"]] == [song["id"]]

    from cisum.api.db import session_factory
    from cisum.api.models import Upload
    from cisum.api.storage import get_storage

    with session_factory()() as db:
        up = db.query(Upload).one()
        assert up.rights_confirmed and up.rights_notice_version == notice_version(api)
        assert up.consent_ip and up.consent_user_agent is not None
        assert up.audio_deleted_at is not None
        assert not get_storage().exists(up.storage_key), "audio is deleted after processing"

    events = api.get(f"/api/songs/{song['id']}/events")
    assert events.headers["content-type"].startswith("text/event-stream")
    data = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")]
    assert data[-1]["status"] == "done"


def test_arrangements_and_files(api):
    register(api)
    song = upload_song(api)
    sid = song["id"]
    easy = api.get(f"/api/songs/{sid}/arrangement", params={"level": "easy"}).json()
    assert easy["level"] == "easy" and easy["transpose"] == -2  # D major -> C major
    assert easy["score"]["key"]["tonic"] == "C"
    assert easy["files"]["pdf"].endswith(f"?transpose={easy['transpose']}")
    hard = api.get(f"/api/songs/{sid}/arrangement", params={"level": "hard", "transpose": "3"}).json()
    assert hard["transpose"] == 3 and hard["score"]["key"]["tonic"] == "F"
    assert api.get(f"/api/songs/{sid}/arrangement", params={"level": "pro"}).status_code == 422
    assert api.get(f"/api/songs/{sid}/arrangement", params={"transpose": "9"}).status_code == 422

    for ext, magic in (("mid", b"MThd"), ("pdf", b"%PDF-"), ("musicxml", b"<?xml")):
        r = api.get(easy["files"][{"mid": "midi"}.get(ext, ext)])
        assert r.status_code == 200, (ext, r.text[:200])
        assert r.content.startswith(magic)
        assert "attachment" in r.headers["content-disposition"]


def test_other_users_cannot_see_songs(api):
    register(api)
    song = upload_song(api)
    api.cookies.clear()
    register(api, "other@example.com")
    assert api.get(f"/api/songs/{song['id']}").status_code == 404
    assert api.get(f"/api/songs/{song['id']}/analysis").status_code == 404


def test_failed_processing_reports_reason(api, monkeypatch):
    from cisum.engine.audio import AudioError
    from cisum.worker import tasks

    def boom(path, progress):
        raise AudioError("not_audio", "This file couldn't be read as audio.")

    monkeypatch.setattr(tasks, "run_analysis", boom)
    register(api)
    song = upload_song(api)
    song = api.get(f"/api/songs/{song['id']}").json()
    assert song["status"] == "failed"
    assert song["error"] == {"code": "not_audio", "message": "This file couldn't be read as audio."}
    assert api.get(f"/api/songs/{song['id']}/arrangement").status_code == 409


def test_same_recording_is_analyzed_once(api):
    register(api)
    upload_song(api, "First")
    upload_song(api, "Second")
    assert len(api.analysis_calls) == 1


def test_delete_song(api):
    register(api)
    song = upload_song(api)
    assert api.delete(f"/api/songs/{song['id']}", headers=CSRF).status_code == 204
    assert api.get(f"/api/songs/{song['id']}").status_code == 404
    assert api.get("/api/songs").json()["songs"] == []


# ---------------------------------------------------------------- editing

def test_edit_chords_and_key(api):
    register(api)
    sid = upload_song(api)["id"]
    analysis = api.get(f"/api/songs/{sid}/analysis").json()
    chords = [{"start": c["start"], "end": c["end"], "symbol": c["symbol"]} for c in analysis["chords"]]

    bad = [dict(chords[0], symbol="Hzz")] + chords[1:]
    r = api.patch(f"/api/songs/{sid}/analysis", json={"chords": bad}, headers=CSRF)
    assert r.status_code == 422 and "'Hzz'" in r.json()["detail"]

    chords[1]["symbol"] = "Bm7"
    r = api.patch(f"/api/songs/{sid}/analysis", json={"chords": chords, "key": [{"start": 0, "tonic": "B", "mode": "minor"}]}, headers=CSRF)
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["version"] == 2
    assert edited["chords"][1]["symbol"] == "Bm7" and edited["chords"][1]["edited"] is True
    assert edited["key"][0]["name"] == "B minor"
    assert api.get(f"/api/songs/{sid}").json()["analysis_version"] == 2
    arr = api.get(f"/api/songs/{sid}/arrangement", params={"level": "medium", "transpose": "0"}).json()
    assert arr["analysis_version"] == 2
    assert arr["score"]["chords"][1]["symbol"] == "Bm7"

    overlapping = [{"start": 0, "end": 6, "symbol": "C"}, {"start": 4, "end": 8, "symbol": "G"}]
    assert api.patch(f"/api/songs/{sid}/analysis", json={"chords": overlapping}, headers=CSRF).status_code == 422


# ---------------------------------------------------------------- sharing and reports

def _share(api, sid):
    r = api.post(f"/api/songs/{sid}/shares", json={"level": "medium", "transpose": 0}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()


def test_share_and_revoke(api):
    register(api)
    sid = upload_song(api)["id"]
    share = _share(api, sid)
    assert share["url"] == f"/s/{share['slug']}"
    api.cookies.clear()
    public = api.get(f"/api/public/shares/{share['slug']}")
    assert public.status_code == 200 and public.json()["title"] == "My Song"
    assert api.get(public.json()["files"]["midi"]).content.startswith(b"MThd")
    api.post("/api/auth/login", json={"email": "user@example.com", "password": "correct horse"})
    assert api.delete(f"/api/shares/{share['slug']}", headers=CSRF).status_code == 204
    assert api.get(f"/api/public/shares/{share['slug']}").status_code == 404


def _report(api, slug, reason="copyright", sworn=True):
    return api.post(
        f"/api/public/shares/{slug}/reports",
        json={"reason": reason, "details": "This is my song.", "reporter_name": "Rights Holder", "reporter_email": "rh@example.com", "sworn_statement": sworn},
        headers=CSRF,  # the web app sends it on every write, logged in or not
    )


def test_copyright_reports_strikes_and_ban(api):
    register(api)
    songs = [upload_song(api, f"Song {i}", data=AUDIO + bytes([i]))["id"] for i in range(3)]
    shares = [_share(api, sid)["slug"] for sid in songs]
    api.cookies.clear()

    assert _report(api, shares[0], sworn=False).status_code == 422
    r = _report(api, shares[0])
    assert r.status_code == 201 and "hidden" in r.json()["message"]
    assert api.get(f"/api/public/shares/{shares[0]}").status_code == 404, "hidden while under review"

    register(api, "admin@example.com")
    reports = api.get("/api/admin/reports").json()["reports"]
    assert len(reports) == 1 and reports[0]["uploader"]["email"] == "user@example.com"
    r = api.post(f"/api/admin/reports/{reports[0]['id']}/resolve", json={"action": "uphold"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["uploader"]["strikes"] == 1
    assert api.post(f"/api/admin/reports/{reports[0]['id']}/resolve", json={"action": "uphold"}, headers=CSRF).status_code == 409

    for slug in shares[1:]:
        _report(api, slug)
    for rep in api.get("/api/admin/reports").json()["reports"]:
        api.post(f"/api/admin/reports/{rep['id']}/resolve", json={"action": "uphold"}, headers=CSRF)
    upheld = api.get("/api/admin/reports", params={"status": "upheld"}).json()["reports"]
    assert len(upheld) == 3 and upheld[0]["uploader"]["banned"] is True

    api.cookies.clear()
    r = api.post("/api/auth/login", json={"email": "user@example.com", "password": "correct horse"})
    assert r.status_code == 403


def test_rejected_report_restores_share(api):
    register(api)
    slug = _share(api, upload_song(api)["id"])["slug"]
    api.cookies.clear()
    _report(api, slug)
    register(api, "admin@example.com")
    rep = api.get("/api/admin/reports").json()["reports"][0]
    api.post(f"/api/admin/reports/{rep['id']}/resolve", json={"action": "reject", "note": "Public domain."}, headers=CSRF)
    assert api.get(f"/api/public/shares/{slug}").status_code == 200


def test_admin_only(api):
    register(api)
    assert api.get("/api/admin/reports").status_code == 403


def test_video_upload_accepted(api):
    register(api)
    v = notice_version(api)
    for name, ct in (("clip.mp4", "video/mp4"), ("clip.mov", "video/quicktime"), ("clip.mp4", "application/octet-stream")):
        r = api.post(
            "/api/uploads",
            json={"filename": name, "content_type": ct, "size_bytes": 120 * 1024 * 1024, "rights_confirmed": True, "rights_notice_version": v},
            headers=CSRF,
        )
        assert r.status_code == 201, (name, ct, r.text)


def test_single_user_mode(api, monkeypatch):
    from cisum.api import config

    monkeypatch.setenv("CISUM_SINGLE_USER", "true")
    config.get_settings.cache_clear()
    me = api.get("/api/auth/me").json()
    assert me["single_user"] is True and me["is_admin"] is True
    song = upload_song(api)  # no account, no login
    assert api.get(f"/api/songs/{song['id']}").json()["status"] == "done"
    # The local account can't be logged into (its email isn't even a valid login).
    assert api.post("/api/auth/login", json={"email": me["email"], "password": "anything at all"}).status_code in (401, 422)


# ---------------------------------------------------------------- S3 storage

def test_s3_storage(monkeypatch, tmp_path):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    from cisum.api.config import Settings
    from cisum.api.storage import S3Storage

    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="cisum")
        s = S3Storage(Settings(storage="s3", s3_bucket="cisum", s3_prefix="app"))
        s.put_bytes("songs/a/analysis.json", b"{}", "application/json")
        assert s.exists("songs/a/analysis.json") and s.size("songs/a/analysis.json") == 2
        assert s.get_bytes("songs/a/analysis.json") == b"{}"
        f = tmp_path / "x.bin"
        f.write_bytes(b"abc")
        s.put_file("songs/a/v1/x.bin", f)
        s.download("songs/a/v1/x.bin", tmp_path / "y.bin")
        assert (tmp_path / "y.bin").read_bytes() == b"abc"
        url = s.presign_put("uploads/u/1/original.mp3", "audio/mpeg")
        assert url and "X-Amz-Signature" in url
        s.delete_prefix("songs/a/")
        assert not s.exists("songs/a/analysis.json")
