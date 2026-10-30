from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuthToken, Song, User
from .security import token_hash

SESSION_COOKIE = "cisum_session"
CSRF_HEADER = "x-cisum-csrf"
LOCAL_USER_EMAIL = "you@this-computer"


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def _local_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        # "!" never matches a password hash, so this account can't be logged into remotely.
        db.add(User(email=LOCAL_USER_EMAIL, password_hash="!", is_admin=True))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if get_settings().single_user:
        return _local_user(db)
    token = _token_from(request)
    if not token:
        return None
    row = db.get(AuthToken, token_hash(token))
    if row is None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return row.user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Please log in.")
    if user.banned:
        raise HTTPException(403, "This account has been suspended after repeated copyright reports.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only.")
    return user


def owned_song(song_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Song:
    song = db.get(Song, song_id)
    if song is None or song.user_id != user.id or song.deleted_at is not None:
        raise HTTPException(404, "Song not found.")
    return song


def client_ip(request: Request, trust_proxy: bool) -> str | None:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
