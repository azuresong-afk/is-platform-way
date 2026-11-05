"""Вход, обновление токена, выход, JWKS, профиль (контракт v1, п. 2; v1.1, п. 2.4)."""

from __future__ import annotations

import base64
import binascii
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import access, audit, service_accounts, sessions, users
from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import Principal, client_ip, principal_allow_temporary
from ..models import AuditLog, User
from ..security import keys, passwords

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
    # Пароль задан администратором: оболочка сразу открывает смену пароля (docs/SECURITY.md, п. 6).
    password_change_required: bool = False


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
        password_change_required=user.password_temporary,
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
    response.headers["Cache-Control"] = "no-store"
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
        detail = err.value if err else "invalid"
        failed = JSONResponse({"detail": detail}, status_code=401, headers={"Cache-Control": "no-store"})
        _clear_cookie(failed)
        return failed
    user = db.get(User, issued.record.user_id)
    out = _token_out(db, user)
    db.commit()
    _set_cookie(response, issued.cookie_value)
    response.headers["Cache-Control"] = "no-store"
    return out


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@router.post(
    "/auth/platform-token",
    response_model=PlatformTokenOut,
    responses={401: {"description": "Сессия недействительна"}},
)
def platform_token(request: Request, db: Session = Depends(get_db)):
    """Токен оболочки для API платформы (контракт v1.1, п. 2.6): aud=["platform"], по refresh-cookie.

    Cookie не ротируется (ротацию ведёт /auth/refresh), но проверяется по тем же правилам:
    повторное предъявление использованной cookie отзывает семейство.
    """
    s = get_settings()
    user, rec, err = sessions.check(db, request.cookies.get(s.refresh_cookie_name))
    if err is not None or user is None:
        if err == sessions.RefreshError.REUSED and rec is not None:
            audit.record(
                db,
                action="auth.refresh_reuse",
                actor_sub=str(rec.user_id),
                result="denied",
                ip=client_ip(request),
                details={"family_id": str(rec.family_id)},
            )
        db.commit()
        detail = err.value if err else "invalid"
        return JSONResponse({"detail": detail}, status_code=401, headers={"Cache-Control": "no-store"})
    token = keys.sign(db, access.platform_claims(user), ttl_seconds=s.platform_token_ttl_seconds)
    db.commit()
    return JSONResponse(
        PlatformTokenOut(access_token=token, expires_in=s.platform_token_ttl_seconds).model_dump(),
        headers={"Cache-Control": "no-store"},
    )


class ServiceTokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


def _oauth_error(code: int, error: str, description: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if code == 401:
        headers["WWW-Authenticate"] = 'Basic realm="platform"'
    return JSONResponse({"error": error, "error_description": description}, status_code=code, headers=headers)


def _basic_credentials(request: Request) -> tuple[str, str] | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(auth[6:].strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    cid, sep, secret = raw.partition(":")
    return (unquote(cid), unquote(secret)) if sep else None


@router.post(
    "/auth/token",
    response_model=ServiceTokenOut,
    responses={400: {"description": "Неверный запрос"}, 401: {"description": "Неверные учётные данные"}},
)
def service_token(
    request: Request,
    grant_type: str = Form(""),
    client_id: str = Form("", max_length=100),
    client_secret: str = Form("", max_length=200),
    db: Session = Depends(get_db),
):
    """Токен сервисной учётной записи (контракт v1.1, п. 2.2): client credentials, без refresh."""
    if grant_type != "client_credentials":
        return _oauth_error(400, "unsupported_grant_type", "Поддерживается только client_credentials")
    basic = _basic_credentials(request)
    if basic is not None:
        client_id, client_secret = basic
    if not client_id or not client_secret:
        return _oauth_error(400, "invalid_request", "Нужны client_id и client_secret")
    ip = client_ip(request)
    sa, err = service_accounts.authenticate(db, client_id, client_secret)
    if err is not None or sa is None:
        audit.record(
            db,
            action="auth.service_token",
            actor_sub=f"svc:{sa.id}" if sa else None,
            actor_name=f"svc:{client_id[:90]}",
            result="failure" if err == service_accounts.ClientError.INVALID_CLIENT else "denied",
            ip=ip,
            details={"reason": err.value if err else "invalid_client"},
        )
        db.commit()
        if err == service_accounts.ClientError.TARGET_UNAVAILABLE:
            return _oauth_error(400, "invalid_target", "Целевой продукт не установлен")
        return _oauth_error(401, "invalid_client", "Неверные учётные данные сервиса или запись отключена")
    s = get_settings()
    token = keys.sign(db, service_accounts.claims(db, sa))
    sa.last_used_at = utcnow()
    audit.record(
        db,
        action="auth.service_token",
        actor_sub=f"svc:{sa.id}",
        actor_name=f"svc:{sa.client_id}",
        object=f"product/{sa.target_product}",
        ip=ip,
    )
    db.commit()
    return JSONResponse(
        ServiceTokenOut(access_token=token, expires_in=s.access_ttl_seconds).model_dump(),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    s = get_settings()
    rec, ok = sessions.find(db, request.cookies.get(s.refresh_cookie_name))
    if rec is not None and ok:
        sessions.revoke_family(db, rec.family_id, "logout")
        user = db.get(User, rec.user_id)
        audit.record(
            db,
            action="auth.logout",
            actor_sub=str(rec.user_id),
            actor_name=user.display_name if user else None,
            ip=client_ip(request),
        )
        db.commit()
    response.status_code = 204
    _clear_cookie(response)
    return response


@router.get("/.well-known/jwks.json")
def jwks(response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=600"
    return keys.jwks(db)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=passwords.MIN_LENGTH, max_length=1024)


def _temporary_set_by(db: Session, user: User) -> AuditLog | None:
    """Кто и откуда задал временный пароль: последняя запись user.create / user.password."""
    return db.scalar(
        select(AuditLog)
        .where(
            AuditLog.product == audit.PLATFORM,
            AuditLog.object == f"user/{user.username}",
            AuditLog.action.in_(("user.create", "user.password")),
        )
        .order_by(AuditLog.time.desc(), AuditLog.id.desc())
        .limit(1)
    )


@router.post(
    "/auth/password",
    response_model=TokenOut,
    responses={
        400: {"description": "Новый пароль совпадает с текущим"},
        403: {"description": "Неверный текущий пароль или запись заблокирована"},
    },
)
def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    p: Principal = Depends(principal_allow_temporary),
    db: Session = Depends(get_db),
) -> TokenOut:
    """Смена своего пароля (в том числе временного, заданного администратором).

    Текущий пароль проверяется как при входе: неудачи считаются в блокировку после
    LOGIN_MAX_FAILURES. Все сессии закрываются, выдаётся новая — с ролями.
    """
    user = p.user
    ip = client_ip(request)
    if user.auth_source != "local":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Пароль внешней учётной записи меняется в её источнике"
        )
    result, _ = users.check_login(db, user.username, body.current_password)
    if result != users.LoginResult.OK:
        audit.record(
            db,
            action="auth.password_change",
            actor_sub=str(user.id),
            actor_name=user.display_name,
            object=f"user/{user.username}",
            result="failure" if result == users.LoginResult.BAD_CREDENTIALS else "denied",
            ip=ip,
            details={"reason": result.value},
        )
        db.commit()
        bad = result == users.LoginResult.BAD_CREDENTIALS
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Неверный текущий пароль" if bad else _LOGIN_ERRORS[result]
        )
    if passwords.verify_password(body.new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Новый пароль должен отличаться от текущего")
    was_temporary = user.password_temporary
    details: dict = {"was_temporary": was_temporary}
    sod = False
    if was_temporary:
        # Временный пароль сменили с того же адреса, откуда его задал администратор:
        # возможно, под записью вошёл он сам (docs/SECURITY.md, п. 6). Подсказка, не доказательство.
        set_by = _temporary_set_by(db, user)
        if set_by is not None:
            details["set_by"] = set_by.actor_name
            sod = bool(ip) and set_by.ip == ip and set_by.actor_sub != str(user.id)
            details["same_ip_as_admin"] = sod
    user.password_hash = passwords.hash_password(body.new_password)
    user.password_temporary = False
    user.updated_at = utcnow()
    sessions.revoke_user(db, user.id, "password_changed")
    issued = sessions.start_session(db, user, request.headers.get("user-agent", ""), ip)
    out = _token_out(db, user)
    audit.record(
        db,
        action="auth.password_change",
        actor_sub=str(user.id),
        actor_name=user.display_name,
        object=f"user/{user.username}",
        ip=ip,
        details=details,
        sod=sod,
    )
    db.commit()
    _set_cookie(response, issued.cookie_value)
    response.headers["Cache-Control"] = "no-store"
    return out


@router.get("/me")
def me(p: Principal = Depends(principal_allow_temporary), db: Session = Depends(get_db)) -> dict:
    u = p.user
    if u.password_temporary:
        # Как в токене: до смены временного пароля прав нет.
        return {
            "id": str(u.id),
            "username": u.username,
            "name": u.display_name,
            "email": u.email,
            "auth_source": u.auth_source,
            "platform_admin": False,
            "products": {},
            "projects": [],
            "password_change_required": True,
        }
    return {
        "id": str(u.id),
        "username": u.username,
        "name": u.display_name,
        "email": u.email,
        "auth_source": u.auth_source,
        "platform_admin": u.is_platform_admin,
        "products": access.effective_roles(db, u),
        "projects": access.effective_projects(db, u),
        "password_change_required": False,
    }
