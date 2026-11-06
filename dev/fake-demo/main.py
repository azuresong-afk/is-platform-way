"""Заглушка «Демо» — четвёртый продукт для проверки модульности (roadmap §1а, шаг М.1).

Платформа ничего не знает о нём заранее: он подключается только через .env
(PLATFORM_PRODUCTS=…,demo и DEMO_API_UPSTREAM), а сводку отдаёт в общем формате
data.kpis[] (контракт v1.1, п. 10.1), поэтому карточка на Главной рисуется без доработки оболочки.
"""

from fakeproduct.app import ProductSpec, make_app, seed

MANIFEST = {
    "id": "demo",
    "title": "Демо",
    "subtitle": "проверка подключения продукта",
    "icon": "box",
    "base_path": "/demo/",
    "api_base": "/api/demo/",
    "version": "0.0.0-fake",
    "roles": {"admin": "Администратор", "editor": "Редактор", "viewer": "Наблюдатель"},
    "admin_roles": ["admin"],
    "nav": [{"id": "items", "label": "Записи", "path": "/demo/items", "icon": "list-checks", "perm": "view"}],
    "search_url": "/api/demo/search",
    "health_url": "/api/demo/health/ready",
    "summary_url": "/api/demo/summary",
    # Мгновенная блокировка (контракт v1.1, п. 6.5) — без доработки платформы, только подписка.
    "events": {"webhook": "/events/platform", "subscribe": ["platform.user.blocked"]},
}


def summary(project: str) -> dict:
    s = seed(project, "demo")
    return {
        "kpis": [
            {"label": "Записи", "value": s % 120, "link": f"/demo/items?project={project}"},
            {"label": "Требуют внимания", "value": s % 7, "severity": "high"},
            {"label": "Критичные", "value": s % 3, "severity": "critical"},
            {"label": "Статус", "value": "в работе", "severity": "info"},
        ],
        "note": "Данные заглушки: меняются только от проекта.",
    }


def objects(project: str) -> list[dict]:
    return [
        {
            "kind": "item",
            "title": "Запись №7: проверка подключения",
            "subtitle": "Демо · Наблюдатель",
            "link": f"/demo/items/7?project={project}",
            "severity": "info",
        }
    ]


app = make_app(ProductSpec(manifest=MANIFEST, summary=summary, objects=objects))
