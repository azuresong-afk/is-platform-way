"""Сводный реестр активов (шаг 2.4): события продуктов, ручная правка, CSV, чтение с фильтрами."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Asset, AuditLog, Event
from tests.helpers import bearer, login
from tests.test_access_admin import _mk_project, _mk_user
from tests.test_events import envelope, post


def _admin(client):
    return bearer(login(client)[0])


def _asset_event(project_id, *, kind="upserted", source="scanner", time="2026-11-04T10:00:00Z", **data):
    body = {
        "asset_id": 101,
        "address": "10.0.0.5",
        "hostname": "web-01",
        "os_family": "linux",
        "os": "Ubuntu 22.04",
        "owner": "ИТ-отдел",
        "criticality": "high",
        "tags": ["dmz"],
        "groups": ["Веб"],
        "last_seen_at": "2026-11-04T09:59:00Z",
        **data,
    }
    return envelope(
        type=f"{source}.asset.{kind}",
        source=source,
        project_id=project_id,
        subject="asset/101",
        time=time,
        data=body,
    )


def _send(client, env, product="scanner", secret="scanner-secret"):
    r = post(client, env, product=product, secret=secret)
    assert r.status_code == 202, r.text


def _list(client, h, pid, **params):
    r = client.get(f"/projects/{pid}/assets", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json(), int(r.headers["X-Total-Count"])


def test_event_creates_asset_and_manual_field_wins(client, db):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    _send(client, _asset_event(pid))
    items, total = _list(client, h, pid)
    assert total == 1
    a = items[0]
    assert a["address"] == "10.0.0.5" and a["hostname"] == "web-01" and a["criticality"] == "high"
    assert a["sources"] == [
        {"product": "scanner", "external_id": "101", "seen_at": "2026-11-04T09:59:00.000000Z"}
    ]

    # ручная правка владельца и критичности
    r = client.patch(f"/assets/{a['id']}", json={"owner": "СОК", "criticality": "critical"}, headers=h)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["manual_fields"]) == ["criticality", "owner"]

    # новое событие «Сканера» не перетирает ручные поля, остальное обновляет
    _send(
        client,
        _asset_event(
            pid, time="2026-11-04T11:00:00Z", owner="Кто-то", criticality="low", hostname="web-01.corp"
        ),
    )
    a = client.get(f"/assets/{a['id']}", headers=h).json()
    assert a["owner"] == "СОК" and a["criticality"] == "critical"
    assert a["hostname"] == "web-01.corp"

    # сброс ручного поля возвращает значение из продукта
    r = client.patch(f"/assets/{a['id']}", json={"reset": ["owner"]}, headers=h)
    assert r.json()["owner"] == "Кто-то" and r.json()["manual_fields"] == ["criticality"]
    assert r.json()["sources"][1]["product"] == "scanner"  # platform + scanner
    actions = {x.action for x in db.scalars(select(AuditLog).where(AuditLog.action.like("asset.%")))}
    assert actions == {"asset.update"}
    # правка публикует своё событие для подписчиков
    assert db.scalar(select(Event).where(Event.type == "platform.asset.upserted")) is not None


def test_stale_event_ignored_and_delete_removes_source(client, db):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    _send(client, _asset_event(pid, time="2026-11-04T12:00:00Z", hostname="new"))
    _send(client, _asset_event(pid, time="2026-11-04T11:00:00Z", hostname="old"))
    items, _ = _list(client, h, pid)
    assert items[0]["hostname"] == "new"

    # другой продукт знает о том же активе: sources[] из двух записей
    _send(
        client,
        _asset_event(pid, source="vm", asset_id="t-9", time="2026-11-04T12:30:00Z", address=" 10.0.0.5 "),
        product="vm",
        secret="vm-secret",
    )
    items, total = _list(client, h, pid)
    assert total == 1 and [s["product"] for s in items[0]["sources"]] == ["scanner", "vm"]
    _, total = _list(client, h, pid, source="vm")
    assert total == 1

    _send(client, _asset_event(pid, kind="deleted", time="2026-11-04T13:00:00Z"))
    items, total = _list(client, h, pid)
    assert total == 1 and [s["product"] for s in items[0]["sources"]] == ["vm"]
    _send(
        client,
        _asset_event(pid, kind="deleted", source="vm", time="2026-11-04T13:00:00Z"),
        product="vm",
        secret="vm-secret",
    )
    assert _list(client, h, pid)[1] == 0


def test_bad_asset_event_is_accepted_but_ignored(client, db):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    _send(client, _asset_event(str(uuid.uuid4())))  # неизвестный проект
    _send(client, _asset_event(pid, address="не адрес!"))
    _send(client, _asset_event(None))
    assert db.scalar(select(Asset)) is None


def test_manual_asset_survives_product_delete(client, db):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    r = client.post(f"/projects/{pid}/assets", json={"address": "10.0.0.5", "owner": "СОК"}, headers=h)
    assert r.status_code == 201, r.text
    assert client.post(f"/projects/{pid}/assets", json={"address": "10.0.0.5"}, headers=h).status_code == 409
    _send(client, _asset_event(pid))
    _send(client, _asset_event(pid, kind="deleted", time="2026-11-04T13:00:00Z"))
    items, total = _list(client, h, pid)
    assert total == 1 and items[0]["owner"] == "СОК" and items[0]["hostname"] == ""
    assert [s["product"] for s in items[0]["sources"]] == ["platform"]

    r = client.delete(f"/assets/{items[0]['id']}", headers=h)
    assert r.status_code == 204
    assert db.scalar(select(AuditLog).where(AuditLog.action == "asset.delete")) is not None


def test_csv_import(client, db):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    _send(client, _asset_event(pid))
    csv_text = (
        "Адрес;Имя хоста;Владелец;Критичность;Теги\n"
        "10.0.0.5;;Бухгалтерия;Критическая;pci, dmz\n"
        "10.0.0.6;db-01;ДБА;medium;\n"
        "bad address!;x;;;\n"
        "10.0.0.7;;;ужасная;\n"
        "10.0.0.6;db-01;ДБА;medium;\n"
    )
    files = {"file": ("assets.csv", csv_text.encode("cp1251"), "text/csv")}

    r = client.post(f"/projects/{pid}/assets/import?dry_run=true", files=files, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1 and r.json()["dry_run"] is True
    assert _list(client, h, pid)[1] == 1  # пробный прогон ничего не сохранил

    r = client.post(f"/projects/{pid}/assets/import", files=files, headers=h)
    rep = r.json()
    assert (rep["rows"], rep["created"], rep["updated"], rep["unchanged"], rep["error_count"]) == (
        5,
        1,
        1,
        1,
        2,
    )
    assert [e["line"] for e in rep["errors"]] == [4, 5]

    a = next(x for x in _list(client, h, pid)[0] if x["address"] == "10.0.0.5")
    assert a["owner"] == "Бухгалтерия" and a["criticality"] == "critical" and a["tags"] == ["pci", "dmz"]
    assert a["hostname"] == "web-01"  # пустая ячейка не меняет поле
    assert sorted(a["manual_fields"]) == ["criticality", "owner", "tags"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "asset.import")).details["created"] == 1

    no_addr = {"file": ("x.csv", b"hostname\nweb\n", "text/csv")}
    assert client.post(f"/projects/{pid}/assets/import", files=no_addr, headers=h).status_code == 422


def test_filters_sort_and_pagination(client):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    rows = [
        ("10.0.0.1", "low", ["a"], "linux"),
        ("10.0.0.2", "critical", ["a", "b"], "windows"),
        ("10.0.0.3", "", [], "linux"),
        ("host.example", "medium", ["b"], "linux"),
    ]
    for i, (addr, crit, tags, fam) in enumerate(rows):
        _send(
            client,
            _asset_event(
                pid, asset_id=i, address=addr, criticality=crit, tags=tags, os_family=fam, hostname=f"h{i}"
            ),
        )
    assert _list(client, h, pid, tag="a")[1] == 2
    assert _list(client, h, pid, criticality=["critical", "none"])[1] == 2
    assert _list(client, h, pid, os_family="LINUX")[1] == 3
    assert _list(client, h, pid, q="EXAMPLE")[1] == 1
    assert _list(client, h, pid, q="%")[1] == 0
    items, _ = _list(client, h, pid, sort="-criticality")
    assert [x["address"] for x in items[:2]] == ["10.0.0.2", "host.example"]
    items, total = _list(client, h, pid, limit=2, offset=2)
    assert total == 4 and [x["address"] for x in items] == ["10.0.0.3", "host.example"]
    facets = client.get(f"/projects/{pid}/assets/facets", headers=h).json()
    assert facets["tags"] == ["a", "b"] and facets["sources"] == ["scanner"]
    assert facets["os_families"] == ["linux", "windows"]
    assert _list(client, h, pid, manual=True)[1] == 0
    assert client.get(f"/projects/{pid}/assets?criticality=bad", headers=h).status_code == 422


def test_access_rules(client):
    h = _admin(client)
    pid = _mk_project(client, h)["id"]
    other = _mk_project(client, h, name="Другой")["id"]
    user = _mk_user(client, h)
    r = client.put(f"/admin/projects/{pid}/members", json=[{"user_id": user["id"]}], headers=h)
    assert r.status_code == 200, r.text
    _send(client, _asset_event(pid))
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    items, total = _list(client, uh, pid)
    assert total == 1
    assert client.get(f"/projects/{other}/assets", headers=uh).status_code == 403
    assert client.patch(f"/assets/{items[0]['id']}", json={"owner": "x"}, headers=uh).status_code == 403
    assert client.get(f"/projects/{pid}/assets").status_code == 401

    # архивный проект — только чтение
    client.post(f"/admin/projects/{pid}/archive", headers=h)
    assert client.patch(f"/assets/{items[0]['id']}", json={"owner": "x"}, headers=h).status_code == 409
