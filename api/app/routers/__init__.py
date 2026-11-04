"""Роутеры API. Порядок подключения — в ROUTERS."""

from . import admin_groups, admin_users, auth, products, projects

ROUTERS: list = [auth, products, projects, admin_users, admin_groups]
