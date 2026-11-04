"""Фабрика FastAPI-заглушки продукта по контракту v1.1.

Поведение для проверки оболочки задаётся переменными окружения:
- FAKE_DELAY_SECONDS — задержка ответов /summary и /search (проверка таймаутов);
- FAKE_FAIL=1 — /summary и /search отвечают 500 (проверка карточки «недоступен»).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from .auth import Caller, JwksCache, require_project, verify_request


@dataclass
class ProductSpec:
    manifest: dict
    # (project_id) -> data для /summary (контракт v1.1, п. 10)
    summary: Callable[[str], dict]
    # (project_id) -> список объектов для поиска {kind,title,subtitle,link,severity?}
    objects: Callable[[str], list[dict]]


STATIC = Path(__file__).with_name("static")


def seed(project_id: str, salt: str) -> int:
    """Стабильное «случайное» число от проекта: данные не меняются между запросами."""
    return int(hashlib.sha256(f"{salt}:{project_id}".encode()).hexdigest()[:8], 16)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_app(spec: ProductSpec, jwks: JwksCache | None = None) -> FastAPI:
    pid = spec.manifest["id"]
    app = FastAPI(title=f"Заглушка: {spec.manifest['title']}")
    app.state.jwks = jwks or JwksCache(
        os.environ.get("PLATFORM_JWKS_URL", "http://platform-api:8000/.well-known/jwks.json")
    )
    app.state.events = []

    def caller(request: Request) -> Caller:
        return verify_request(request, pid, request.app.state.jwks)

    def chaos() -> None:
        delay = float(os.environ.get("FAKE_DELAY_SECONDS", "0") or 0)
        if delay:
            time.sleep(delay)
        if os.environ.get("FAKE_FAIL") == "1":
            raise HTTPException(500, detail="fake failure")

    # Крошечная страница продукта для e2e (шлюз: <ID>_WEB_UPSTREAM = адрес этой же заглушки).
    page = (
        (STATIC / "index.html")
        .read_text(encoding="utf-8")
        .replace("__PRODUCT__", escape(pid))
        .replace("__TITLE__", escape(spec.manifest["title"]))
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/app.js", include_in_schema=False)
    def app_js() -> FileResponse:
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css", include_in_schema=False)
    def app_css() -> FileResponse:
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/manifest")
    def manifest() -> dict:
        return spec.manifest

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict:
        return {"status": "ok"}

    @app.get("/me")
    def me(c: Caller = Depends(caller)) -> dict:
        return {
            "sub": c.sub,
            "username": c.username,
            "name": c.name,
            "roles": c.roles,
            "projects": c.projects,
        }

    @app.get("/summary")
    def summary(project: str | None = Query(None), c: Caller = Depends(caller)) -> dict:
        require_project(c, project)
        chaos()
        return {
            "product": pid,
            "project_id": project,
            "generated_at": now_iso(),
            "link": f"{spec.manifest['base_path']}?project={project}",
            "data": spec.summary(project),
        }

    @app.get("/search")
    def search(
        q: str = Query("", max_length=200),
        project: str | None = Query(None),
        limit: int = Query(8, ge=1, le=50),
        c: Caller = Depends(caller),
    ) -> dict:
        require_project(c, project)
        chaos()
        needle = q.strip().lower()
        items = [
            o for o in spec.objects(project) if needle and needle in (o["title"] + o["subtitle"]).lower()
        ]
        return {"items": items[:limit]}

    webhook = (spec.manifest.get("events") or {}).get("webhook")
    if webhook:

        @app.post(webhook, status_code=202)
        async def receive_event(request: Request) -> dict:
            body = await request.body()
            secret = os.environ.get("PLATFORM_EVENTS_SECRET", "")
            expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not secret or not hmac.compare_digest(expected, request.headers.get("x-signature", "")):
                raise HTTPException(401, detail="bad_signature")
            event = await request.json()
            if any(e["id"] == event.get("id") for e in request.app.state.events):
                return {"duplicate": True}
            request.app.state.events.append(event)
            return {"accepted": True}

        @app.get("/events/received")
        def received(c: Caller = Depends(caller)) -> list[dict]:
            return list(app.state.events)

    return app
