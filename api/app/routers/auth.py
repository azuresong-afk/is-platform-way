"""Вход, обновление токена, выход, JWKS, профиль (контракт v1, п. 2; v1.1, п. 2.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import access, audit, sessions, users
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, current_principal
from ..models import User
from ..security import keys

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class UserBrief(BaseModel):
    id: str
    username: str
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserBrief


def _set_cookie(response: Response, value: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        value,
        max_age=s.refresh_max_days * 86400,
        path=s.refresh_cookie_path,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
    )


def _clear_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        s.refresh_cookie_name,
        path=s.refresh_cookie_path,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
    )


def _token_out(db: Session, user: User) -> TokenOut:
    s = get_settings()
    token = keys.sign(db, access.user_claims(db, user))
    return TokenOut(
        access_token=token,
        expires_in=s.access_ttl_seconds,
        user=UserBrief(id=str(user.id), username=user.username, name=user.display_name),
    )


_LOGIN_ERRORS = {
    users.LoginResult.BAD_CREDENTIALS: "Неверный логин или пароль",
    users.LoginResult.LOCKED: "Учётная запись временно заблокирована после неудачных попыток входа",
    users.LoginResult.INACTIVE: "Учётная запись отключена",
}


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    ip = client_ip(request)
    result, user = users.check_login(db, body.username, body.password)
    if result != users.LoginResult.OK or user is None:
        audit.record(
            db,
            action="auth.login",
            actor_sub=str(user.id) if user else None,
            actor_name=body.username[:100],
            result="failure" if result == users.LoginResult.BAD_CREDENTIALS else "denied",
            ip=ip,
            details={"reason": result.value},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_LOGIN_ERRORS[result])
    issued = sessions.start_session(db, user, request.headers.get("user-agent", ""), ip)
    out = _token_out(db, user)
    audit.record(db, action="auth.login", actor_sub=str(user.id), actor_name=user.display_name, ip=ip)
    db.commit()
    _set_cookie(response, issued.cookie_value)
    return out


@router.post(
    "/auth/refresh", response_model=TokenOut, responses={401: {"description": "Сессия недействительна"}}
)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = client_ip(request)
    issued, rec, err = sessions.rotate(
        db, request.cookies.get(s.refresh_cookie_name), request.headers.get("user-agent", ""), ip
    )
    if err is not None or issued is None:
        if err == sessions.RefreshError.REUSED and rec is not None:
            audit.record(
                db,
                action="auth.refresh_reuse",
                actor_sub=str(rec.user_id),
                result="denied",
                ip=ip,
                details={"family_id": str(rec.family_id)},
            )
        db.commit()
        failed = JSONResponse({"detail": err.value if err else "invalid"}, status_code=401)
        _clear_cookie(failed)
        return failed
    user = db.get(User, issued.record.user_id)
    out = _token_out(db, user)
    db.commit()
    _set_cookie(response, issued.cookie_value)
    return out


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    s = get_settings()
    rec, ok = sessions.find(db, request.cookies.get(s.refresh_cookie_name))
    if rec is not None and ok:
        sessions.revoke_family(db, rec.family_id, "logout")
        audit.record(db, action="auth.logout", actor_sub=str(rec.user_id), ip=client_ip(request))
        db.commit()
    response.status_code = 204
    _clear_cookie(response)
    return response


@router.get("/.well-known/jwks.json")
def jwks(response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=600"
    return keys.jwks(db)


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict:
    u = p.user
    return {
        "id": str(u.id),
        "username": u.username,
        "name": u.display_name,
        "email": u.email,
        "auth_source": u.auth_source,
        "platform_admin": u.is_platform_admin,
        "products": access.effective_roles(db, u),
        "projects": access.effective_projects(db, u),
    }
