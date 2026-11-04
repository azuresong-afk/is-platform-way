"""Роутеры API. Порядок подключения — в ROUTERS."""

from . import admin_groups, admin_users, auth, projects

ROUTERS: list = [auth, projects, admin_users, admin_groups]
