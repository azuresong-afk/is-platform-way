"""Отправить тестовое событие в платформу от имени продукта (для ручной проверки шины).

    python dev/send_event.py --product scanner --secret "$SCANNER_EVENTS_SECRET" \
        --url http://127.0.0.1:18090/api/platform/events --type scanner.run.finished

Печатает код ответа и тело. Повторный запуск с тем же --id проверяет идемпотентность.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18090/api/platform/events")
    ap.add_argument("--product", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--type", default=None, help="по умолчанию <product>.test.sent")
    ap.add_argument("--id", default=None)
    ap.add_argument("--project", default=None)
    ap.add_argument("--data", default='{"note": "тестовое событие"}', help="JSON")
    a = ap.parse_args()
    envelope = {
        "id": a.id or str(uuid.uuid4()),
        "type": a.type or f"{a.product}.test.sent",
        "source": a.product,
        "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_id": a.project,
        "subject": "dev/send_event",
        "data": json.loads(a.data),
    }
    body = json.dumps(envelope, ensure_ascii=False).encode()
    sig = "sha256=" + hmac.new(a.secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        a.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Platform-Product": a.product,
            "X-Event-Id": envelope["id"],
            "X-Signature": sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - адрес задаёт разработчик
            print(r.status, r.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode())
        return 1
    print("id:", envelope["id"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
