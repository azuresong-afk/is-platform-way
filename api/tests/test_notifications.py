"""Центр уведомлений (шаг 3.2): событие с notify появляется у адресата."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app import events, users
from app.models import Notification
from tests.helpers import bearer, login
from tests.test_events import envelope, post


def _user(db, name):
    u = users.create_user(db, username=name, password="long-password-1")
    db.commit()
    return u


def _token(client, name):
    return bearer(login(client, name, "long-password-1")[0])


def test_event_with_notify_reaches_addressees_only(client, db):
    alice, bob, _carol = _user(db, "alice"), _user(db, "bob"), _user(db, "carol")
    env = envelope(
        type="vm.ticket.created",
        source="vm",
        notify={
            "users": [str(alice.id), str(bob.id), str(alice.id), str(uuid.uuid4()), "not-a-uuid"],
            "title": "Вам назначена заявка №125",
            "link": "/vm/tickets/125",
        },
    )
    assert post(client, env, product="vm", secret="vm-secret").status_code == 202
    # повторная доставка того же события не дублирует уведомления
    assert post(client, env, product="vm", secret="vm-secret").status_code == 200
    assert len(db.scalars(select(Notification)).all()) == 2

    a = _token(client, "alice")
    r = client.get("/notifications", headers=a)
    assert r.status_code == 200, r.text
    assert r.headers["X-Total-Count"] == "1" and r.headers["X-Unread-Count"] == "1"
    item = r.json()[0]
    assert item["title"] == "Вам назначена заявка №125"
    assert item["link"] == "/vm/tickets/125"
    assert item["product"] == "vm" and item["product_title"] and item["event_type"] == "vm.ticket.created"
    assert item["read_at"] is None

    c = _token(client, "carol")
    assert client.get("/notifications", headers=c).json() == []
    assert client.get("/notifications/unread-count", headers=c).json() == {"unread": 0}
    # чужое уведомление — как несуществующее
    assert client.post(f"/notifications/{item['id']}/read", headers=c).status_code == 404
    assert client.get("/notifications").status_code == 401


def test_read_unread_and_read_all(client, db):
    alice = _user(db, "alice")
    sources = (
        ("scanner", "scanner-secret", "scanner.run.finished"),
        ("vm", "vm-secret", "vm.ticket.created"),
    )
    for src, secret, typ in sources:
        for i in range(2):
            env = envelope(type=typ, source=src, notify={"users": [str(alice.id)], "title": f"{src} {i}"})
            assert post(client, env, product=src, secret=secret).status_code == 202
    a = _token(client, "alice")
    assert client.get("/notifications/unread-count", headers=a).json() == {"unread": 4}

    first = client.get("/notifications?limit=1", headers=a)
    assert first.headers["X-Total-Count"] == "4" and len(first.json()) == 1
    nid = first.json()[0]["id"]
    r = client.post(f"/notifications/{nid}/read", headers=a)
    assert r.status_code == 200 and r.json()["read_at"]
    assert client.get("/notifications/unread-count", headers=a).json() == {"unread": 3}
    assert len(client.get("/notifications?unread=true", headers=a).json()) == 3
    assert client.post(f"/notifications/{nid}/unread", headers=a).json()["read_at"] is None

    assert len(client.get("/notifications?product=scanner", headers=a).json()) == 2
    r = client.post("/notifications/read-all", json={"product": "scanner"}, headers=a)
    assert r.json() == {"updated": 2}
    assert client.get("/notifications/unread-count", headers=a).json() == {"unread": 2}
    assert client.post("/notifications/read-all", headers=a).json() == {"updated": 2}
    assert client.get("/notifications/unread-count", headers=a).json() == {"unread": 0}


def test_event_without_notify_and_platform_publish(client, db):
    alice = _user(db, "alice")
    assert post(client, envelope()).status_code == 202
    assert db.scalars(select(Notification)).all() == []

    # своё событие платформы тоже может адресовать уведомление
    events.publish(
        db, "platform.user.blocked", {"sub": "x"}, notify={"users": [str(alice.id)], "title": "Проверка"}
    )
    db.commit()
    a = _token(client, "alice")
    item = client.get("/notifications", headers=a).json()[0]
    assert item["product"] == "platform" and item["product_title"] == "Платформа"


def test_deleted_user_drops_notifications(client, db):
    alice = _user(db, "alice")
    env = envelope(notify={"users": [str(alice.id)], "title": "x"})
    assert post(client, env).status_code == 202
    db.delete(alice)
    db.commit()
    assert db.scalars(select(Notification)).all() == []
