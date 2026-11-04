"""Роутеры API. Порядок подключения — в ROUTERS."""

from . import (
    admin_groups,
    admin_keys,
    admin_service_accounts,
    admin_users,
    assets,
    audit,
    auth,
    events,
    notifications,
    products,
    projects,
)

ROUTERS: list = [
    auth,
    products,
    projects,
    admin_users,
    admin_groups,
    admin_service_accounts,
    events,
    audit,
    assets,
    admin_keys,
    notifications,
]
