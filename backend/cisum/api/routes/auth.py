from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import SESSION_COOKIE, current_user
from ..models import AuthToken, User, now
from ..schemas import AuthOut, Credentials, UserOut
from ..security import hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _start_session(db: Session, user: User, response: Response) -> str:
    settings = get_settings()
    token = new_token()
    db.add(AuthToken(token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(days=settings.session_days)))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return token


@router.post("/register", status_code=201, response_model=AuthOut)
def register(body: Credentials, response: Response, db: Session = Depends(get_db)) -> AuthOut:
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=body.email in get_settings().admin_email_set,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    token = _start_session(db, user, response)
    return AuthOut(user=UserOut.of(user), token=token)


@router.post("/login", response_model=AuthOut)
def login(body: Credentials, response: Response, db: Session = Depends(get_db)) -> AuthOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password.")
    if user.banned:
        raise HTTPException(403, "This account has been suspended after repeated copyright reports.")
    token = _start_session(db, user, response)
    return AuthOut(user=UserOut.of(user), token=token)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if token:
        row = db.get(AuthToken, token_hash(token))
        if row is not None:
            db.delete(row)
            db.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.of(user)
