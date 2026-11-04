"""Заглушка «Аттестации»: манифест, сводка, поиск по контракту v1.1."""

from fakeproduct.app import ProductSpec, make_app, seed

MANIFEST = {
    "id": "grc",
    "title": "Аттестация",
    "subtitle": "ФСТЭК №117/21/239",
    "icon": "shield-check",
    "base_path": "/grc/",
    "api_base": "/api/grc/",
    "version": "0.0.0-fake",
    "roles": {
        "admin": "Администратор",
        "methodologist": "Методист",
        "assessor": "Аттестатор",
        "approve": "Утверждение (надбавка)",
        "viewer": "Наблюдатель",
    },
    "admin_roles": ["admin"],
    "nav": [
        {"id": "systems", "label": "Объекты", "path": "/grc/systems", "icon": "building-2", "perm": "view"},
        {
            "id": "documents",
            "label": "Документы",
            "path": "/grc/documents",
            "icon": "file-text",
            "perm": "view",
        },
    ],
    "search_url": "/api/grc/search",
    "health_url": "/api/grc/health/ready",
    "summary_url": "/api/grc/summary",
    "events": {
        "webhook": "/events/platform",
        "subscribe": ["scanner.run.finished", "platform.keys.rotated", "platform.project.updated"],
    },
}


def summary(project: str) -> dict:
    s = seed(project, "grc")
    total = 12 + s % 10
    return {
        "systems": 1 + s % 4,
        "measures_percent": 40 + s % 55,
        "documents": {"ready": s % total, "total": total},
    }


def objects(project: str) -> list[dict]:
    return [
        {
            "kind": "system",
            "title": "ГИС «Учёт обращений» (К2)",
            "subtitle": "Приказ ФСТЭК №117",
            "link": f"/grc/systems/1?project={project}",
        },
        {
            "kind": "measure",
            "title": "УПД.3 Управление информационными потоками",
            "subtitle": "Не реализована",
            "link": f"/grc/measures/УПД.3?project={project}",
        },
    ]


app = make_app(ProductSpec(manifest=MANIFEST, summary=summary, objects=objects))
