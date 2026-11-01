from datetime import timedelta

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import User


def issue_session(user_id: int) -> str:
    exp = utcnow() + timedelta(hours=settings.session_hours)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret, algorithm="HS256")


def _user_from_header(authorization: str | None, db: Session) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please sign in again")
    return db.get(User, int(payload["sub"]))


def optional_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User | None:
    return _user_from_header(authorization, db)


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    user = _user_from_header(authorization, db)
    if not user:
        raise HTTPException(401, "Sign in required")
    return user


def require_staff(x_staff_pin: str | None = Header(None)) -> None:
    if x_staff_pin != settings.staff_pin:
        raise HTTPException(403, "Invalid staff PIN")
