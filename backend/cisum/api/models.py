from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class Upload(Base):
    """One uploaded file plus the rights consent given for it."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    declared_size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | uploaded | completed
    # Consent record: who agreed to which wording, when, from where.
    rights_confirmed: Mapped[bool] = mapped_column(Boolean)
    rights_notice_version: Mapped[str] = mapped_column(String(40))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage_message: Mapped[str] = mapped_column(String(200), default="Waiting in line…")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_version: Mapped[int] = mapped_column(Integer, default=0)
    backends: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship()
    upload: Mapped[Upload] = relationship()


def _slug() -> str:
    return secrets.token_urlsafe(9)


class Share(Base):
    __tablename__ = "shares"

    slug: Mapped[str] = mapped_column(String(32), primary_key=True, default=_slug)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    level: Mapped[str] = mapped_column(String(10))
    transpose: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # pending review of a copyright report
    taken_down_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    song: Mapped[Song] = relationship()

    @property
    def publicly_visible(self) -> bool:
        return (
            self.revoked_at is None
            and self.taken_down_at is None
            and not self.hidden
            and self.song.deleted_at is None
            and not self.song.owner.banned
        )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    share_slug: Mapped[str] = mapped_column(ForeignKey("shares.slug"), index=True)
    reason: Mapped[str] = mapped_column(String(20))  # copyright | other
    details: Mapped[str] = mapped_column(Text)
    reporter_name: Mapped[str] = mapped_column(String(200))
    reporter_email: Mapped[str] = mapped_column(String(320))
    sworn_statement: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | upheld | rejected
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    share: Mapped[Share] = relationship()
