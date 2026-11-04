"""Сводный журнал аудита (шаг 2.5): audit.recorded продуктов + действия платформы, фильтры, выгрузка."""

from __future__ import annotations

import csv
import io
import json
import uuid

from sqlalchemy import func, select

from app.models import AuditLog, Event
from app.routers import audit as audit_router
from tests.helpers import bearer, login
from tests.test_access_admin import _mk_project, _mk_user
from tests.test_events import envelope, post


def _admin(client):
    return bearer(login(client)[0])


def _recorded(project_id=None, product="scanner", **data):
    payload = {
        "time": "2026-11-04T10:00:00Z",
        "actor": {"sub": "u-42", "name": "Петров П. П."},
        "action": "run.start",
        "object": "run/7",
        "result": "success",
        "ip": "10.0.0.5",
        "details": {"targets": 3},
        **data,
    }
    return envelope(
        type="audit.recorded",
        source=product,
        project_id=project_id,
        subject="",
        data=payload,
    )


def test_product_record_lands_in_log_once(client, db):
    h = _admin(client)
    proj = _mk_project(client, h)
    env = _recorded(proj["id"])
    assert post(client, env).status_code == 202
    assert post(client, env).status_code == 200  # повтор — не дублируется

    rows = client.get("/audit", params={"product": "scanner"}, headers=h)
    assert rows.status_code == 200
    assert rows.headers["X-Total-Count"] == "1"
    row = rows.json()[0]
    assert row["product"] == "scanner" and row["product_title"]
    assert row["actor_sub"] == "u-42" and row["actor_name"] == "Петров П. П."
    assert row["action"] == "run.start" and row["object"] == "run/7"
    assert row["project_id"] == proj["id"] and row["project_name"] == proj["name"]
    assert row["ip"] == "10.0.0.5" and row["details"] == {"targets": 3}
    assert row["event_id"] == env["id"]
    assert row["time"].startswith("2026-11-04T10:00:00")


def test_product_record_minimal_and_long_fields(client, db):
    h = _admin(client)
    env = _recorded(actor=None, object="x" * 1000, time=None, details=None)
    env["data"] = {k: v for k, v in env["data"].items() if v is not None}
    assert post(client, env).status_code == 202
    row = client.get("/audit", params={"action": "run.start"}, headers=h).json()[0]
    assert row["actor_sub"] is None and len(row["object"]) == 300 and row["details"] == {}


def test_invalid_record_rejected_with_422(client, db):
    for bad in ({"action": ""}, {"result": "maybe"}, {"time": "2026-11-04T10:00:00"}, {"details": "строка"}):
        env = _recorded(**bad)
        r = post(client, env)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"] == "rejected"
        # событие тоже не сохранено: продукт исправит запись и отправит снова
        assert db.get(Event, uuid.UUID(env["id"])) is None
    # в пачке — 422 только у плохой записи
    good, bad = _recorded(), _recorded(action="")
    r = post(client, [good, bad])
    assert [x["status"] for x in r.json()["results"]] == [202, 422]
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_id.is_not(None))) == 1


def test_platform_actions_and_filters(client, db):
    h = _admin(client)
    user = _mk_user(client, h)  # user.create
    # неудачный вход — auth.login с результатом failure
    client.post("/auth/login", json={"username": "ivanov", "password": "wrong-password"})
    proj = _mk_project(client, h, name="Проект Б")
    post(client, _recorded(proj["id"]))
    post(
        client,
        _recorded(product="vm", action="ticket.close", result="denied"),
        product="vm",
        secret="vm-secret",
    )

    def total(**params):
        r = client.get("/audit", params=params, headers=h)
        assert r.status_code == 200, r.text
        return int(r.headers["X-Total-Count"]), r.json()

    n, rows = total(product="platform")
    assert n >= 3 and {"auth.login", "user.create", "project.create"} <= {r["action"] for r in rows}
    assert all(r["product_title"] == "Платформа" for r in rows)
    assert total(product="vm")[0] == 1
    n, rows = total(action="auth.*")
    assert n >= 2 and all(r["action"].startswith("auth.") for r in rows)
    assert total(action="auth")[0] == 0  # без «.*» — точное совпадение
    assert total(result="denied")[1][0]["action"] == "ticket.close"
    _, rows = total(product="platform", action="auth.login", result="failure")
    assert rows and rows[0]["result"] == "failure"
    assert total(project=proj["id"])[0] >= 2  # project.create платформы + run.start продукта
    # часть имени; ILIKE без учёта регистра (SQLite в тестах не приводит кириллицу — проверка регистра на PG)
    assert total(actor="етров")[0] == 2
    assert total(actor="u-42")[0] == 2  # sub целиком
    assert total(actor=user["id"])[0] == 1  # его неудачный вход
    assert total(actor="100%")[0] == 0  # спецсимволы LIKE экранируются
    assert total(**{"from": "2026-11-04T10:00:00Z", "to": "2026-11-04T10:00:01Z"})[0] == 2
    assert total(**{"to": "2026-11-04T10:00:00Z"})[0] == 0

    _, rows = total(limit=2)
    assert len(rows) == 2 and rows[0]["time"] >= rows[1]["time"]  # новые сверху


def test_facets_come_from_log(client):
    h = _admin(client)
    proj = _mk_project(client, h)
    post(client, _recorded(proj["id"]))
    f = client.get("/audit/facets", headers=h).json()
    ids = [p["id"] for p in f["products"]]
    assert ids[0] == "platform" and "scanner" in ids and "vm" not in ids  # vm ничего не присылал
    assert {"id": proj["id"], "title": proj["name"]} in f["projects"]
    assert "run.start" in f["actions"] and "auth.login" in f["actions"]


def test_non_admin_forbidden(client):
    h = _admin(client)
    _mk_user(client, h)
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    for path in ("/audit", "/audit/facets", "/audit/export"):
        assert client.get(path, headers=uh).status_code == 403
    assert client.get("/audit").status_code == 401


def test_export_csv_and_json(client, db):
    h = _admin(client)
    post(client, _recorded(object='=HYPERLINK("http://evil")', details={"note": "Привет"}))
    r = client.get("/audit/export", params={"format": "csv", "product": "scanner"}, headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(text[1:])))
    assert len(rows) == 1
    assert rows[0]["object"].startswith("'=")  # формула обезврежена
    assert json.loads(rows[0]["details"]) == {"note": "Привет"}
    assert rows[0]["actor_name"] == "Петров П. П."

    r = client.get("/audit/export", params={"format": "json"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    data = json.loads(r.content)
    assert any(x["product"] == "scanner" and x["object"].startswith("=") for x in data)  # в JSON — как есть
    # выгрузка сама попадает в журнал
    exports = db.scalars(select(AuditLog).where(AuditLog.action == "audit.export")).all()
    assert [e.details["format"] for e in exports] == ["csv", "json"]
    assert exports[0].details["filters"] == {"product": "scanner"}

    assert client.get("/audit/export", params={"format": "xml"}, headers=h).status_code == 422


def test_export_limit(client, monkeypatch):
    h = _admin(client)
    _admin(client)  # второй вход — в журнале две записи
    monkeypatch.setattr(audit_router, "EXPORT_MAX", 1)
    r = client.get("/audit/export", headers=h)
    assert r.status_code == 422 and "Сузьте фильтр" in r.json()["detail"]
