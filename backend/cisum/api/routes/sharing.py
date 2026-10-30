"""Share links, the public shared view, copyright reports, and the admin review queue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import arrangements
from ..config import get_settings
from ..db import get_db
from ..deps import admin_user, current_user
from ..legal import RIGHTS_NOTICE
from ..models import Report, Share, Song, User, now
from ..schemas import ReportCreate, ReportOut, ReportResolve
from ..storage import get_storage

router = APIRouter(tags=["sharing"])


@router.get("/api/legal/rights-notice")
def rights_notice() -> dict[str, Any]:
    return RIGHTS_NOTICE


@router.delete("/api/shares/{slug}", status_code=204)
def revoke_share(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    share = db.get(Share, slug)
    if share is None or share.song.user_id != user.id:
        raise HTTPException(404, "Share not found.")
    if share.revoked_at is None:
        share.revoked_at = now()
        db.commit()
    return Response(status_code=204)


def _visible_share(slug: str, db: Session) -> Share:
    share = db.get(Share, slug)
    if share is None or not share.publicly_visible or share.song.status != "done":
        raise HTTPException(404, "This arrangement isn't available.")
    return share


@router.get("/api/public/shares/{slug}")
def public_share(slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    share = _visible_share(slug, db)
    song = share.song
    t, score = arrangements.ensure(get_storage(), song, share.level, share.transpose)
    base = f"/api/public/shares/{slug}/files/score"
    return {
        "slug": slug,
        "title": song.title,
        "artist": song.artist,
        "level": share.level,
        "transpose": t,
        "score": score,
        "files": {"musicxml": f"{base}.musicxml", "midi": f"{base}.mid", "pdf": f"{base}.pdf"},
    }


@router.get("/api/public/shares/{slug}/files/{filename}")
def public_file(slug: str, filename: str, db: Session = Depends(get_db)) -> Response:
    share = _visible_share(slug, db)
    stem, _, ext = filename.partition(".")
    if stem != "score":
        raise HTTPException(404, "Not found.")
    data, t = arrangements.file_bytes(get_storage(), share.song, share.level, share.transpose, ext)
    name = arrangements.download_name(share.song, share.level, t, ext)
    return Response(data, media_type=arrangements.CONTENT_TYPES[ext], headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/public/shares/{slug}/reports", status_code=201)
def report_share(slug: str, body: ReportCreate, db: Session = Depends(get_db)) -> dict[str, str]:
    share = db.get(Share, slug)
    if share is None or share.revoked_at is not None or share.taken_down_at is not None:
        raise HTTPException(404, "This arrangement isn't available.")
    if body.reason == "copyright" and not body.sworn_statement:
        raise HTTPException(422, "Copyright reports need the good-faith statement to be confirmed.")
    report = Report(
        share_slug=slug,
        reason=body.reason,
        details=body.details.strip(),
        reporter_name=body.reporter_name.strip(),
        reporter_email=body.reporter_email,
        sworn_statement=body.sworn_statement,
    )
    db.add(report)
    hidden = body.reason == "copyright" and get_settings().auto_hide_on_copyright_report
    if hidden:
        share.hidden = True
    db.commit()
    message = "Thanks. We've received your report and will review it."
    if hidden:
        message += " The arrangement is hidden while we do."
    return {"id": report.id, "message": message}


@router.get("/api/admin/reports")
def list_reports(
    status: str = Query("open"), _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> dict[str, list[ReportOut]]:
    q = select(Report).order_by(Report.created_at.desc())
    if status != "all":
        if status not in ("open", "upheld", "rejected"):
            raise HTTPException(422, "status must be open, upheld, rejected or all")
        q = q.where(Report.status == status)
    return {"reports": [ReportOut.of(r) for r in db.scalars(q).all()]}


@router.post("/api/admin/reports/{report_id}/resolve", response_model=ReportOut)
def resolve_report(report_id: str, body: ReportResolve, admin: User = Depends(admin_user), db: Session = Depends(get_db)) -> ReportOut:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Report not found.")
    if report.status != "open":
        raise HTTPException(409, "This report has already been resolved.")
    report.status = "upheld" if body.action == "uphold" else "rejected"
    report.note = body.note
    report.resolved_at = now()
    report.resolved_by = admin.id
    share = report.share
    song: Song = share.song

    if body.action == "uphold":
        for s in db.scalars(select(Share).where(Share.song_id == song.id, Share.taken_down_at.is_(None))):
            s.taken_down_at = now()
        owner = song.owner
        owner.strikes += 1
        if owner.strikes >= get_settings().strike_limit:
            owner.banned = True
            owned = select(Song.id).where(Song.user_id == owner.id)
            for s in db.scalars(select(Share).where(Share.song_id.in_(owned), Share.taken_down_at.is_(None))):
                s.taken_down_at = now()
    else:
        still_open = db.scalar(
            select(Report.id).where(Report.share_slug == share.slug, Report.status == "open", Report.reason == "copyright", Report.id != report.id)
        )
        if still_open is None:
            share.hidden = False
    db.commit()
    db.refresh(report)
    return ReportOut.of(report)
