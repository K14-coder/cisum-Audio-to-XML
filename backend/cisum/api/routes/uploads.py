from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import client_ip, current_user
from ..jobs import enqueue_song
from ..legal import RIGHTS_NOTICE_VERSION
from ..models import Song, Upload, User
from ..schemas import SongOut, UploadComplete, UploadCreate, UploadTarget, UploadTicket
from ..storage import get_storage

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".webm", ".mp4", ".aif", ".aiff", ".wma"}


def _accepted_type(content_type: str, filename: str) -> bool:
    ct = content_type.split(";")[0].strip().lower()
    if ct.startswith("audio/"):
        return True
    # Browsers label some audio-only containers as video (mic recordings, .m4a on some systems).
    if ct in ("video/webm", "video/mp4", "video/ogg", "application/ogg"):
        return True
    return ct == "application/octet-stream" and Path(filename).suffix.lower() in AUDIO_EXTENSIONS


@router.post("", status_code=201, response_model=UploadTicket)
def create_upload(body: UploadCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> UploadTicket:
    settings = get_settings()
    if not body.rights_confirmed:
        raise HTTPException(422, "Please confirm you have the rights to this song (rights notice).")
    if body.rights_notice_version != RIGHTS_NOTICE_VERSION:
        raise HTTPException(422, "The rights notice has changed. Please read it again and confirm.")
    if not _accepted_type(body.content_type, body.filename):
        raise HTTPException(422, "Please upload an audio file (MP3, WAV, M4A, FLAC, OGG or WebM).")
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(413, f"Files can be up to {settings.max_upload_mb} MB.")

    content_type = body.content_type.split(";")[0].strip().lower()
    upload = Upload(
        user_id=user.id,
        filename=Path(body.filename).name[:255],
        content_type=content_type,
        declared_size=body.size_bytes,
        storage_key="",
        rights_confirmed=True,
        rights_notice_version=body.rights_notice_version,
        consent_ip=client_ip(request, settings.trust_proxy_headers),
        consent_user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    db.add(upload)
    db.flush()
    upload.storage_key = f"uploads/{user.id}/{upload.id}/original{Path(upload.filename).suffix.lower()[:8]}"
    db.commit()

    storage = get_storage()
    presigned = storage.presign_put(upload.storage_key, content_type)
    url = presigned or f"/api/uploads/{upload.id}/content"
    return UploadTicket(
        upload_id=upload.id,
        max_bytes=settings.max_upload_bytes,
        upload=UploadTarget(url=url, headers={"Content-Type": content_type}),
    )


def _own_upload(upload_id: str, user: User, db: Session) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None or upload.user_id != user.id:
        raise HTTPException(404, "Upload not found.")
    return upload


@router.put("/{upload_id}/content", status_code=204)
async def put_content(upload_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """Receives the file when storage is local (S3 uploads go straight to the bucket)."""
    settings = get_settings()
    upload = _own_upload(upload_id, user, db)
    if upload.status != "pending":
        raise HTTPException(409, "This upload has already been received.")
    limit = settings.max_upload_bytes
    received = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise HTTPException(413, f"Files can be up to {settings.max_upload_mb} MB.")
        chunks.append(chunk)
    if received == 0:
        raise HTTPException(422, "The file is empty.")
    get_storage().put_bytes(upload.storage_key, b"".join(chunks), upload.content_type)
    upload.status = "uploaded"
    db.commit()
    return Response(status_code=204)


@router.post("/{upload_id}/complete", status_code=201, response_model=SongOut)
def complete(upload_id: str, body: UploadComplete, user: User = Depends(current_user), db: Session = Depends(get_db)) -> SongOut:
    settings = get_settings()
    upload = _own_upload(upload_id, user, db)
    if upload.status == "completed":
        raise HTTPException(409, "This upload has already been submitted.")
    storage = get_storage()
    size = storage.size(upload.storage_key)
    if size is None:
        raise HTTPException(409, "The file hasn't finished uploading.")
    if size > settings.max_upload_bytes:
        storage.delete(upload.storage_key)
        raise HTTPException(413, f"Files can be up to {settings.max_upload_mb} MB.")
    upload.status = "completed"
    song = Song(user_id=user.id, upload_id=upload.id, title=body.title.strip(), artist=(body.artist or "").strip() or None)
    db.add(song)
    db.commit()
    enqueue_song(song.id)
    db.refresh(song)
    return SongOut.of(song)
