"""Заглушка «Сканера»: манифест, сводка, поиск по контракту v1.1."""

from fakeproduct.app import ProductSpec, make_app, seed

MANIFEST = {
    "id": "scanner",
    "title": "Сканер",
    "subtitle": "уязвимости и соответствие",
    "icon": "radar",
    "base_path": "/scanner/",
    "api_base": "/api/scanner/",
    "version": "0.0.0-fake",
    "roles": {
        "admin": "Администратор",
        "operator": "Оператор",
        "auditor": "Аудитор",
        "cred_audit": "Аудит паролей (надбавка)",
        "host_credentials": "Учётные записи хостов (надбавка)",
    },
    "admin_roles": ["admin"],
    "nav": [
        {
            "id": "overview",
            "label": "Сводка",
            "path": "/scanner/",
            "icon": "layout-dashboard",
            "perm": "view",
        },
        {"id": "runs", "label": "Прогоны", "path": "/scanner/runs", "icon": "play", "perm": "view"},
        {"id": "assets", "label": "Активы", "path": "/scanner/assets", "icon": "server", "perm": "view"},
    ],
    "search_url": "/api/scanner/search",
    "health_url": "/api/scanner/health/ready",
    "summary_url": "/api/scanner/summary",
    "events": {"webhook": "/events/platform", "subscribe": ["vm.remediation.verified"]},
}


def summary(project: str) -> dict:
    s = seed(project, "scanner")
    return {
        "open": {
            "critical": s % 4,
            "high": s % 13,
            "medium": s % 37,
            "low": s % 55,
            "info": s % 120,
        },
        "last_run": {
            "id": s % 1000,
            "name": "Ежемесячный прогон",
            "status": "done" if s % 3 else "partial",
            "finished_at": "2026-11-03T21:14:00Z",
            "link": f"/scanner/runs/{s % 1000}?project={project}",
        },
    }


def objects(project: str) -> list[dict]:
    return [
        {
            "kind": "finding",
            "title": "CVE-2024-6387 — OpenSSH regreSSHion",
            "subtitle": "10.0.0.5:22 · Критический",
            "link": f"/scanner/findings/42?project={project}",
            "severity": "critical",
        },
        {
            "kind": "finding",
            "title": "BDU:2024-04835 — OpenSSH",
            "subtitle": "10.0.0.7:22 · Высокий",
            "link": f"/scanner/findings/43?project={project}",
            "severity": "high",
        },
        {
            "kind": "asset",
            "title": "10.0.0.5 — web-01",
            "subtitle": "Astra Linux 1.7",
            "link": f"/scanner/assets/5?project={project}",
        },
        {
            "kind": "run",
            "title": "Ежемесячный прогон",
            "subtitle": "Завершён 03.11.2026",
            "link": f"/scanner/runs/1?project={project}",
        },
    ]


app = make_app(ProductSpec(manifest=MANIFEST, summary=summary, objects=objects))
