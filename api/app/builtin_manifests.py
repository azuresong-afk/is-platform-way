"""Встроенные манифесты известных продуктов — необязательный запасной вариант.

Нужны только до первого ответа продукта: администратор может заранее выдать роли
«Сканера», «Устранения» и «Аттестации». Новому продукту запись здесь не нужна — до получения
его манифеста платформа показывает минимальный манифест-заглушку (см. products.placeholder_manifest).
"""

from __future__ import annotations

from typing import Any

BUILTIN_MANIFESTS: dict[str, dict[str, Any]] = {
    "scanner": {
        "id": "scanner",
        "title": "Сканер",
        "subtitle": "уязвимости и соответствие",
        "icon": "radar",
        "base_path": "/scanner/",
        "api_base": "/api/scanner/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "operator": "Оператор",
            "auditor": "Аудитор",
            "cred_audit": "Аудит паролей (надбавка)",
            "host_credentials": "Учётные записи хостов (надбавка)",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/scanner/search",
        "health_url": "/api/scanner/health/ready",
        "summary_url": "/api/scanner/summary",
    },
    "vm": {
        "id": "vm",
        "title": "Устранение",
        "subtitle": "управление уязвимостями",
        "icon": "wrench",
        "base_path": "/vm/",
        "api_base": "/api/vm/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "manager": "Руководитель",
            "engineer": "Исполнитель",
            "viewer": "Наблюдатель",
            "remediate_execute": "Запуск исправлений (надбавка)",
            "custom_commands": "Свои команды (надбавка)",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/vm/search",
        "health_url": "/api/vm/health/ready",
        "summary_url": "/api/vm/summary",
    },
    "grc": {
        "id": "grc",
        "title": "Аттестация",
        "subtitle": "ФСТЭК №117/21/239",
        "icon": "shield-check",
        "base_path": "/grc/",
        "api_base": "/api/grc/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "methodologist": "Методист",
            "assessor": "Аттестатор",
            "approve": "Утверждение (надбавка)",
            "viewer": "Наблюдатель",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/grc/search",
        "health_url": "/api/grc/health/ready",
        "summary_url": "/api/grc/summary",
    },
}
