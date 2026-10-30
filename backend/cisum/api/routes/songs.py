from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...engine.chords import merge_adjacent
from ...engine.theory import ChordLabel, ChordParseError, Key, parse_chord
from ...engine.types import LEVELS, ChordSegment, KeySegment
from .. import arrangements
from ..db import get_db, session_factory
from ..deps import current_user, owned_song
from ..models import Share, Song, User, now
from ..schemas import AnalysisEdit, ShareCreate, ShareOut, SongOut, SongPatch
from ..storage import get_storage

router = APIRouter(prefix="/api/songs", tags=["songs"])


@router.get("")
def list_songs(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, list[SongOut]]:
    rows = db.scalars(
        select(Song).where(Song.user_id == user.id, Song.deleted_at.is_(None)).order_by(Song.created_at.desc())
    ).all()
    return {"songs": [SongOut.of(s) for s in rows]}


@router.get("/{song_id}", response_model=SongOut)
def get_song(song: Song = Depends(owned_song)) -> SongOut:
    return SongOut.of(song)


@router.patch("/{song_id}", response_model=SongOut)
def patch_song(body: SongPatch, song: Song = Depends(owned_song), db: Session = Depends(get_db)) -> SongOut:
    changed = False
    if body.title is not None and body.title.strip() != song.title:
        song.title = body.title.strip()
        changed = True
    if "artist" in body.model_fields_set and (body.artist or None) != song.artist:
        song.artist = (body.artist or "").strip() or None
        changed = True
    if changed and song.analysis_version:
        song.analysis_version += 1  # titles are engraved into the files
        _bump_analysis_version(song)
    db.commit()
    return SongOut.of(song)


@router.delete("/{song_id}", status_code=204)
def delete_song(song: Song = Depends(owned_song), db: Session = Depends(get_db)) -> Response:
    song.deleted_at = now()
    for share in db.scalars(select(Share).where(Share.song_id == song.id, Share.revoked_at.is_(None))):
        share.revoked_at = now()
    db.commit()
    storage = get_storage()
    storage.delete_prefix(f"songs/{song.id}/")
    storage.delete(song.upload.storage_key)
    return Response(status_code=204)


@router.get("/{song_id}/events")
async def song_events(request: Request, song: Song = Depends(owned_song)) -> StreamingResponse:
    song_id = song.id

    def snapshot() -> dict[str, Any] | None:
        with session_factory()() as db:
            s = db.get(Song, song_id)
            if s is None:
                return None
            out = SongOut.of(s)
            return {
                "status": out.status,
                "progress": out.progress,
                "stage_message": out.stage_message,
                "error": out.error.model_dump() if out.error else None,
            }

    async def stream():
        last = None
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            state = await run_in_threadpool(snapshot)
            if state is None:
                return
            if state != last:
                yield f"event: status\ndata: {json.dumps(state)}\n\n"
                last = state
                idle = 0.0
                if state["status"] in ("done", "failed"):
                    return
            elif idle >= 15:
                yield ": keep-alive\n\n"
                idle = 0.0
            await asyncio.sleep(0.5)
            idle += 0.5

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{song_id}/analysis")
def get_analysis(song: Song = Depends(owned_song)) -> dict[str, Any]:
    analysis = arrangements.load_analysis(get_storage(), song)
    return analysis.to_dict()


@router.patch("/{song_id}/analysis")
def edit_analysis(body: AnalysisEdit, song: Song = Depends(owned_song), db: Session = Depends(get_db)) -> dict[str, Any]:
    storage = get_storage()
    analysis = arrangements.load_analysis(storage, song)
    total = float(analysis.total_beats)

    if body.key is not None:
        if not body.key:
            raise HTTPException(422, "At least one key is required.")
        keys = []
        for k in sorted(body.key, key=lambda k: k.start):
            try:
                key = Key.parse(k.tonic, k.mode)
            except ValueError:
                raise HTTPException(422, f"Unknown key '{k.tonic} {k.mode}'.") from None
            if k.start >= total:
                raise HTTPException(422, "A key change starts after the end of the song.")
            keys.append(KeySegment(float(k.start), key, 1.0))
        keys[0].start = 0.0
        analysis.key = keys

    if body.chords is not None:
        edits = sorted(body.chords, key=lambda c: c.start)
        old = {(round(c.start, 3), round(c.end, 3)): c for c in analysis.chords}
        segments: list[ChordSegment] = []
        cursor = 0.0
        for c in edits:
            if c.end <= c.start:
                raise HTTPException(422, f"A chord must end after it starts (beat {c.start:g}).")
            if c.start < cursor - 1e-6:
                raise HTTPException(422, f"Chords overlap at beat {c.start:g}.")
            if c.end > total + 1e-6:
                raise HTTPException(422, "A chord runs past the end of the song.")
            try:
                label = parse_chord(c.symbol)
            except ChordParseError:
                raise HTTPException(422, f"Unknown chord symbol '{c.symbol}'.") from None
            if c.start > cursor + 1e-6:
                segments.append(ChordSegment(cursor, c.start, ChordLabel(None), 1.0, True))
            prev = old.get((round(c.start, 3), round(c.end, 3)))
            if prev is not None and prev.label == label:
                segments.append(ChordSegment(c.start, c.end, label, prev.confidence, prev.edited))
            else:
                segments.append(ChordSegment(c.start, c.end, label, 1.0, True))
            cursor = c.end
        if cursor < total:
            segments.append(ChordSegment(cursor, total, ChordLabel(None), 1.0, True))
        analysis.chords = merge_adjacent(segments)

    analysis.version = song.analysis_version + 1
    arrangements.save_analysis(storage, song.id, analysis)
    song.analysis_version = analysis.version
    db.commit()
    return analysis.to_dict()


def _bump_analysis_version(song: Song) -> None:
    storage = get_storage()
    analysis = arrangements.load_analysis(storage, song, require_done=False)
    analysis.version = song.analysis_version
    arrangements.save_analysis(storage, song.id, analysis)


def _files(song_id: str, level: str, transpose: int) -> dict[str, str]:
    return {ext_name: f"/api/songs/{song_id}/files/{level}.{ext}?transpose={transpose}" for ext_name, ext in (("musicxml", "musicxml"), ("midi", "mid"), ("pdf", "pdf"))}


def _level(level: str) -> str:
    if level not in LEVELS:
        raise HTTPException(422, "level must be easy, medium or hard")
    return level


@router.get("/{song_id}/arrangement")
def get_arrangement(
    level: str = Query("medium"), transpose: str | None = Query(None), song: Song = Depends(owned_song)
) -> dict[str, Any]:
    level = _level(level)
    t, score = arrangements.ensure(get_storage(), song, level, arrangements.parse_transpose(transpose))
    return {
        "song_id": song.id,
        "level": level,
        "transpose": t,
        "analysis_version": song.analysis_version,
        "score": score,
        "files": _files(song.id, level, t),
    }


@router.get("/{song_id}/files/{filename}")
def get_file(filename: str, transpose: str | None = Query(None), song: Song = Depends(owned_song)) -> Response:
    level, _, ext = filename.partition(".")
    level = _level(level)
    data, t = arrangements.file_bytes(get_storage(), song, level, arrangements.parse_transpose(transpose), ext)
    name = arrangements.download_name(song, level, t, ext)
    return Response(
        data,
        media_type=arrangements.CONTENT_TYPES[ext],
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, max-age=60"},
    )


@router.post("/{song_id}/shares", status_code=201, response_model=ShareOut)
def create_share(body: ShareCreate, song: Song = Depends(owned_song), user: User = Depends(current_user), db: Session = Depends(get_db)) -> ShareOut:
    if song.status != "done":
        raise HTTPException(409, "This song is still being processed.")
    share = Share(song_id=song.id, created_by=user.id, level=body.level, transpose=body.transpose)
    db.add(share)
    db.commit()
    db.refresh(share)
    return ShareOut.of(share)


@router.get("/{song_id}/shares")
def list_shares(song: Song = Depends(owned_song), db: Session = Depends(get_db)) -> dict[str, list[ShareOut]]:
    rows = db.scalars(select(Share).where(Share.song_id == song.id).order_by(Share.created_at.desc())).all()
    return {"shares": [ShareOut.of(s) for s in rows]}
