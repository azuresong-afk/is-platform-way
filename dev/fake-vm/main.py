"""Заглушка «Устранения»: манифест, сводка, поиск по контракту v1.1."""

from fakeproduct.app import ProductSpec, make_app, seed

MANIFEST = {
    "id": "vm",
    "title": "Устранение",
    "subtitle": "управление уязвимостями",
    "icon": "wrench",
    "base_path": "/vm/",
    "api_base": "/api/vm/",
    "version": "0.0.0-fake",
    "roles": {
        "admin": "Администратор",
        "manager": "Руководитель",
        "engineer": "Исполнитель",
        "viewer": "Наблюдатель",
        "remediate_execute": "Запуск исправлений (надбавка)",
        "custom_commands": "Свои команды (надбавка)",
    },
    "admin_roles": ["admin"],
    "nav": [
        {"id": "queue", "label": "Очередь", "path": "/vm/queue", "icon": "list-checks", "perm": "view"},
        {
            "id": "windows",
            "label": "Окна обслуживания",
            "path": "/vm/windows",
            "icon": "calendar",
            "perm": "view",
        },
    ],
    "search_url": "/api/vm/search",
    "health_url": "/api/vm/health/ready",
    "summary_url": "/api/vm/summary",
    "events": {
        "webhook": "/events/platform",
        "subscribe": [
            "scanner.run.finished",
            "scanner.asset.*",
            "platform.keys.rotated",
            "platform.project.updated",
            "platform.user.blocked",
        ],
    },
}


def summary(project: str) -> dict:
    s = seed(project, "vm")
    return {
        "open_tickets": s % 40,
        "overdue_tickets": s % 5,
        "verified_week": s % 17,
        "next_window": {
            "id": s % 100,
            "title": "Плановое окно: серверы БД",
            "starts_at": "2026-11-08T19:00:00Z",
            "link": f"/vm/windows/{s % 100}?project={project}",
        },
    }


def objects(project: str) -> list[dict]:
    return [
        {
            "kind": "ticket",
            "title": "№125 Обновить openssh-server",
            "subtitle": "Назначена: Петров П. П. · Высокий",
            "link": f"/vm/tickets/125?project={project}",
            "severity": "high",
        },
        {
            "kind": "window",
            "title": "Плановое окно: серверы БД",
            "subtitle": "08.11.2026 22:00",
            "link": f"/vm/windows/1?project={project}",
        },
    ]


app = make_app(ProductSpec(manifest=MANIFEST, summary=summary, objects=objects))
