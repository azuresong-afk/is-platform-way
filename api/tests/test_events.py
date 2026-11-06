"""Шина событий (шаг 2.3): приём с HMAC, идемпотентность, подписки, доставка, повторы."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app import events
from app.db import utcnow
from app.models import AuditLog, Delivery, Event, Product, Subscription
from tests.helpers import bearer, login

SECRET = "scanner-secret"  # conftest: SCANNER_EVENTS_SECRET


def envelope(**kw):
    return {
        "id": str(uuid.uuid4()),
        "type": "scanner.run.finished",
        "source": "scanner",
        "time": "2026-11-04T16:54:52Z",
        "project_id": None,
        "subject": "run/1",
        "data": {"run_id": 1, "status": "done"},
        **kw,
    }


def post(client, payload, product="scanner", secret=SECRET, headers=None):
    body = json.dumps(payload).encode()
    h = {
        "X-Platform-Product": product,
        "X-Signature": events.sign(secret, body),
        "Content-Type": "application/json",
    }
    if isinstance(payload, dict):
        h["X-Event-Id"] = payload.get("id", "")
    h.update(headers or {})
    return client.post("/events", content=body, headers=h)


@pytest.fixture
def vm_subscribed(db):
    """У «Устранения» в манифесте подписка на scanner.*."""
    vm = db.get(Product, "vm")
    vm.manifest = {
        **vm.manifest,
        "events": {"webhook": "/events/platform", "subscribe": ["scanner.*", "bad pattern"]},
    }
    events.sync_subscription(db, vm)
    db.commit()
    return db.scalar(select(Subscription).where(Subscription.product_id == "vm"))


def test_accept_duplicate_and_signature(client, db):
    env = envelope()
    r = post(client, env)
    assert r.status_code == 202, r.text
    r = post(client, env)
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert db.scalar(select(Event).where(Event.id == uuid.UUID(env["id"]))) is not None

    assert post(client, envelope(), secret="wrong").status_code == 401
    assert post(client, envelope(source="grc", type="grc.x.y"), product="grc", secret="").status_code == 401
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "event.receive")).all()
    assert len(denied) == 2 and all(a.result == "denied" for a in denied)


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "vm"},  # source не совпадает с X-Platform-Product
        {"type": "vm.ticket.created"},  # type не своего продукта
        {"type": "NoDots"},
        {"id": "not-uuid"},
        {"time": "2026-11-04T16:54:52"},  # без часового пояса
        {"notify": {"users": ["u1"], "title": "x", "link": "https://evil.example/"}},
        {"notify": {"users": ["u1"], "title": "x", "link": "//evil.example/"}},
    ],
)
def test_invalid_envelope_422(client, bad):
    assert post(client, envelope(**bad)).status_code == 422


def test_event_id_header_must_match(client):
    r = post(client, envelope(), headers={"X-Event-Id": str(uuid.uuid4())})
    assert r.status_code == 422


def test_audit_recorded_allowed_from_any_product(client):
    env = envelope(type="audit.recorded", data={"action": "run.start"})
    assert post(client, env).status_code == 202


def test_batch_207(client):
    good, dup = envelope(), envelope()
    post(client, dup)
    r = post(client, [good, dup, envelope(type="bad")])
    assert r.status_code == 207
    statuses = [x["status"] for x in r.json()["results"]]
    assert statuses == [202, 200, 422]
    assert post(client, []).status_code == 422


def test_subscription_from_manifest_and_delivery(client, db, vm_subscribed):
    assert vm_subscribed.types == ["scanner.*"]
    env = envelope()
    post(client, env)
    post(client, envelope(type="scanner.asset.upserted"))
    db.expire_all()
    deliveries = db.scalars(select(Delivery)).all()
    assert len(deliveries) == 2 and all(d.status == "pending" for d in deliveries)

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        assert request.url == httpx.URL("http://vm.test/events/platform")
        assert request.headers["X-Platform-Product"] == "platform"
        assert request.headers["X-Signature"] == events.sign("vm-secret", body)
        seen.append(json.loads(body))
        return httpx.Response(202)

    client_http = httpx.Client(transport=httpx.MockTransport(handler))
    assert events.run_due(client_http) == 2
    assert {e["type"] for e in seen} == {"scanner.run.finished", "scanner.asset.upserted"}
    first = next(e for e in seen if e["id"] == env["id"])
    assert first["subject"] == "run/1" and first["time"] == "2026-11-04T16:54:52Z"
    db.expire_all()
    assert all(d.status == "ok" and d.delivered_at for d in db.scalars(select(Delivery)))
    assert events.run_due(client_http) == 0


def test_source_does_not_receive_own_events(client, db):
    scanner = db.get(Product, "scanner")
    scanner.manifest = {**scanner.manifest, "events": {"webhook": "/hook", "subscribe": ["*"]}}
    events.sync_subscription(db, scanner)
    db.commit()
    post(client, envelope())
    db.expire_all()
    assert db.scalars(select(Delivery)).all() == []


def test_retries_1_5_15_60_then_dead_and_redeliver(client, db, vm_subscribed):
    env = envelope()
    post(client, env)
    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    expected = [1, 5, 15, 60]
    for minutes in expected:
        assert events.run_due(failing) == 1
        db.expire_all()
        d = db.scalar(select(Delivery))
        assert d.status == "failed" and d.last_status_code == 500 and "boom" in d.last_error
        delay = d.next_attempt_at.replace(tzinfo=None) - utcnow().replace(tzinfo=None)
        assert timedelta(minutes=minutes) - timedelta(seconds=5) < delay <= timedelta(minutes=minutes)
        assert events.run_due(failing) == 0  # срок ещё не пришёл
        d.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert events.run_due(failing) == 1
    db.expire_all()
    d = db.scalar(select(Delivery))
    assert d.status == "dead" and d.attempts == 5 and d.next_attempt_at is None

    h = bearer(login(client)[0])
    listed = client.get("/admin/events?delivery=problems", headers=h)
    assert listed.headers["X-Total-Count"] == "1" and listed.json()[0]["delivery"] == "dead"
    r = client.post(f"/admin/events/{env['id']}/redeliver", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deliveries"][0]["status"] == "pending"
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert events.run_due(ok) == 1
    db.expire_all()
    assert db.scalar(select(Delivery)).status == "ok"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "event.redeliver")) is not None


def test_network_error_is_retried(client, db, vm_subscribed):
    post(client, envelope())

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    events.run_due(httpx.Client(transport=httpx.MockTransport(down)))
    db.expire_all()
    d = db.scalar(select(Delivery))
    assert d.status == "failed" and "ConnectError" in d.last_error


def test_disabled_subscription_gets_nothing_and_manifest_sync_keeps_flag(client, db, vm_subscribed):
    h = bearer(login(client)[0])
    subs = client.get("/admin/subscriptions", headers=h).json()
    assert subs[0]["product_id"] == "vm" and subs[0]["types"] == ["scanner.*"]
    r = client.patch(f"/admin/subscriptions/{subs[0]['id']}", json={"is_active": False}, headers=h)
    assert r.status_code == 200 and r.json()["is_active"] is False
    events.sync_subscription(db, db.get(Product, "vm"))
    db.commit()
    db.expire_all()
    assert db.get(Subscription, uuid.UUID(subs[0]["id"])).is_active is False
    post(client, envelope())
    db.expire_all()
    assert db.scalars(select(Delivery)).all() == []


def test_platform_publishes_project_updated(client, db, vm_subscribed):
    vm_subscribed.types = ["platform.*"]
    db.commit()
    h = bearer(login(client)[0])
    pid = client.post(
        "/admin/projects", json={"name": "П", "client": "", "contract_ref": ""}, headers=h
    ).json()["id"]
    client.post(f"/admin/projects/{pid}/archive", headers=h)
    db.expire_all()
    evs = db.scalars(
        select(Event).where(Event.type == "platform.project.updated").order_by(Event.received_at)
    ).all()
    assert [e.data["status"] for e in evs] == ["active", "archived"]
    assert all(e.source == "platform" and str(e.project_id) == pid for e in evs)
    assert len(db.scalars(select(Delivery)).all()) == 2


def test_platform_publishes_user_blocked(client, db, vm_subscribed):
    """Мгновенная блокировка в продуктах (шаг 5.6, контракт v1.1, п. 6.5)."""
    from datetime import UTC, datetime

    from app import users
    from tests.helpers import claims

    vm_subscribed.types = ["platform.user.blocked"]
    victim = users.create_user(db, username="victim", password="pw-123456")
    db.commit()
    token = login(client, "victim", "pw-123456", platform=False)[0]
    h = bearer(login(client)[0])
    assert client.patch(f"/admin/users/{victim.id}", json={"is_active": False}, headers=h).status_code == 200
    db.expire_all()
    ev = db.scalars(select(Event).where(Event.type == "platform.user.blocked")).one()
    assert ev.source == "platform" and ev.project_id is None and ev.subject == f"user/{victim.id}"
    assert set(ev.data) == {"sub", "blocked_at", "hold_until"} and ev.data["sub"] == str(victim.id)
    at = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()  # noqa: E731
    # Токен, выданный до блокировки, попадает под правило iat <= blocked_at и истекает до hold_until.
    c = claims(token)
    assert c["iat"] <= at(ev.data["blocked_at"]) and c["exp"] + 60 <= at(ev.data["hold_until"])
    assert len(db.scalars(select(Delivery)).all()) == 1


def test_blocked_event_data_rounds_up():
    from datetime import UTC, datetime

    from app import users

    d = users.blocked_event_data(uuid.UUID(int=1), datetime(2026, 11, 6, 21, 0, 0, 200000, tzinfo=UTC))
    assert d == {
        "sub": "00000000-0000-0000-0000-000000000001",
        "blocked_at": "2026-11-06T21:00:01Z",
        "hold_until": "2026-11-06T21:16:01Z",
    }
    exact = users.blocked_event_data(uuid.UUID(int=1), datetime(2026, 11, 6, 21, 0, 0, tzinfo=UTC))
    assert exact["blocked_at"] == "2026-11-06T21:00:00Z"


def test_handler_hook_runs_in_same_transaction(client, db):
    calls = []

    @events.on("scanner.asset.*")
    def remember(session, event):
        calls.append(event.type)

    try:
        post(client, envelope(type="scanner.asset.upserted"))
        post(client, envelope())
    finally:
        events._handlers.remove(("scanner.asset.*", remember))
    assert calls == ["scanner.asset.upserted"]


def test_admin_event_detail_and_filters(client, db, vm_subscribed):
    env = envelope(notify={"users": ["u1"], "title": "Готово", "link": "/scanner/runs/1"})
    post(client, env)
    post(client, envelope(type="scanner.asset.upserted"))
    h = bearer(login(client)[0])
    r = client.get("/admin/events?type=scanner.run", headers=h)
    assert r.headers["X-Total-Count"] == "1"
    d = client.get(f"/admin/events/{env['id']}", headers=h).json()
    assert d["notify"]["title"] == "Готово" and d["deliveries"][0]["product_id"] == "vm"
    assert client.get("/admin/events?source=scanner", headers=h).headers["X-Total-Count"] == "2"


def test_matches():
    assert events.matches("scanner.*", "scanner.run.finished")
    assert not events.matches("scanner.*", "scannerx.run")
    assert events.matches("*", "vm.ticket.created")
    assert events.matches("vm.ticket.created", "vm.ticket.created")
