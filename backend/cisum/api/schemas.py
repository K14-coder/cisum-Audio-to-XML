from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import Report, Share, Song, User

Level = Literal["easy", "medium", "hard"]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or " " in v:
            raise ValueError("enter a valid email address")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    is_admin: bool
    strikes: int
    banned: bool

    @classmethod
    def of(cls, u: User) -> "UserOut":
        return cls(id=u.id, email=u.email, is_admin=u.is_admin, strikes=u.strikes, banned=u.banned)


class AuthOut(BaseModel):
    user: UserOut
    token: str


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    rights_confirmed: bool
    rights_notice_version: str


class UploadTarget(BaseModel):
    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]


class UploadTicket(BaseModel):
    upload_id: str
    max_bytes: int
    upload: UploadTarget


class UploadComplete(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str | None = Field(default=None, max_length=200)


class SongError(BaseModel):
    code: str
    message: str


class SongOut(BaseModel):
    id: str
    title: str
    artist: str | None
    status: str
    progress: float
    stage_message: str
    error: SongError | None
    duration_s: float | None
    analysis_version: int
    created_at: datetime

    @classmethod
    def of(cls, s: Song) -> "SongOut":
        return cls(
            id=s.id,
            title=s.title,
            artist=s.artist,
            status=s.status,
            progress=round(s.progress, 3),
            stage_message=s.stage_message,
            error=SongError(code=s.error_code or "internal", message=s.error_message or "") if s.status == "failed" else None,
            duration_s=s.duration_s,
            analysis_version=s.analysis_version,
            created_at=s.created_at,
        )


class SongPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    artist: str | None = Field(default=None, max_length=200)


class ChordEdit(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    symbol: str = Field(max_length=20)


class KeyEdit(BaseModel):
    start: float = Field(ge=0)
    tonic: str = Field(max_length=3)
    mode: Literal["major", "minor"]


class AnalysisEdit(BaseModel):
    chords: list[ChordEdit] | None = None
    key: list[KeyEdit] | None = None


class ShareCreate(BaseModel):
    level: Level
    transpose: int = Field(ge=-12, le=12)


class ShareOut(BaseModel):
    slug: str
    url: str
    song_id: str
    level: str
    transpose: int
    created_at: datetime
    revoked: bool
    taken_down: bool

    @classmethod
    def of(cls, s: Share) -> "ShareOut":
        return cls(
            slug=s.slug,
            url=f"/s/{s.slug}",
            song_id=s.song_id,
            level=s.level,
            transpose=s.transpose,
            created_at=s.created_at,
            revoked=s.revoked_at is not None,
            taken_down=s.taken_down_at is not None,
        )


class ReportCreate(BaseModel):
    reason: Literal["copyright", "other"]
    details: str = Field(min_length=1, max_length=5000)
    reporter_name: str = Field(min_length=1, max_length=200)
    reporter_email: str = Field(min_length=3, max_length=320)
    sworn_statement: bool = False

    @field_validator("reporter_email")
    @classmethod
    def _email(cls, v: str) -> str:
        return Credentials._email(v)


class ReportResolve(BaseModel):
    action: Literal["uphold", "reject"]
    note: str | None = Field(default=None, max_length=2000)


class ReportOut(BaseModel):
    id: str
    status: str
    reason: str
    details: str
    reporter_name: str
    reporter_email: str
    created_at: datetime
    resolved_at: datetime | None
    note: str | None
    share: dict
    song: dict
    uploader: dict

    @classmethod
    def of(cls, r: Report) -> "ReportOut":
        song = r.share.song
        owner = song.owner
        return cls(
            id=r.id,
            status=r.status,
            reason=r.reason,
            details=r.details,
            reporter_name=r.reporter_name,
            reporter_email=r.reporter_email,
            created_at=r.created_at,
            resolved_at=r.resolved_at,
            note=r.note,
            share={"slug": r.share.slug, "level": r.share.level, "transpose": r.share.transpose},
            song={"id": song.id, "title": song.title, "artist": song.artist},
            uploader={"id": owner.id, "email": owner.email, "strikes": owner.strikes, "banned": owner.banned},
        )
