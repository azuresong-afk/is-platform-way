"""Настройки platform-api из переменных окружения (.env)."""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from functools import lru_cache

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Продукты установки задаются только окружением (roadmap §1а): PLATFORM_PRODUCTS — список id,
# для каждого id — переменные <ID>_API_UPSTREAM, <ID>_WEB_UPSTREAM, <ID>_EVENTS_SECRET.
DEFAULT_PLATFORM_PRODUCTS = "scanner,vm,grc"
# id продукта — сегмент пути (/api/<id>/, /<id>/), значение aud в JWT и префикс переменных.
PRODUCT_ID_RE = re.compile(r"^[a-z][a-z0-9]{1,19}$")
# Пути, которые занимает сама платформа.
RESERVED_PRODUCT_IDS = frozenset({"platform", "api", "admin", "login", "assets", "fonts"})


def parse_product_ids(raw: str) -> list[str]:
    """Разбирает PLATFORM_PRODUCTS: id через запятую и/или пробел; порядок сохраняется."""
    out: list[str] = []
    for pid in re.split(r"[\s,]+", raw.strip()):
        if not pid or pid in out:
            continue
        if not PRODUCT_ID_RE.match(pid):
            raise RuntimeError(
                f"PLATFORM_PRODUCTS: недопустимый id «{pid}» — нужны строчные латинские буквы и цифры, "
                "2–20 символов, первая — буква"
            )
        if pid in RESERVED_PRODUCT_IDS:
            raise RuntimeError(f"PLATFORM_PRODUCTS: id «{pid}» зарезервирован платформой")
        out.append(pid)
    return out


@dataclass(frozen=True)
class ProductConfig:
    id: str
    # Внутренний адрес API продукта (без /api/<id>), например http://scanner-app:8000
    api_upstream: str
    events_secret: str
    web_upstream: str = ""
    # Место в PLATFORM_PRODUCTS: порядок вкладок, если манифест не задаёт свой.
    position: int = 0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./platform.sqlite3"
    # 32 байта в base64: ключ AES-GCM для приватных ключей подписи и секретов.
    platform_secret_key: str = ""
    issuer: str = "platform"

    access_ttl_seconds: int = 900
    refresh_ttl_hours: int = 12
    refresh_max_days: int = 7
    # Окно, в которое повторное предъявление refresh-токена считается гонкой
    # двух вкладок, а не кражей.
    refresh_reuse_grace_seconds: int = 10
    # Сколько прежний ключ остаётся в JWKS после смены: не меньше TTL access-токена,
    # иначе уже выданные токены перестанут проверяться раньше срока.
    jwks_retain_seconds: int = 1800
    # Плановая ротация ключа подписи: раз в key_rotation_days дней. Новый ключ
    # сначала публикуется в JWKS со статусом next и начинает подписывать не раньше
    # чем через key_next_lead_seconds — дольше кэша JWKS в продуктах (600 с).
    key_rotation_days: int = 90
    key_next_lead_seconds: int = 1200
    key_rotation_check_seconds: int = 60

    login_max_failures: int = 5
    login_lock_minutes: int = 15

    cookie_secure: bool = True
    refresh_cookie_name: str = "platform_refresh"
    refresh_cookie_path: str = "/api/platform/auth"

    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "Администратор платформы"

    # Продукты установки (id через запятую). Продукт из списка с пустым <ID>_API_UPSTREAM
    # в кабинете не появляется.
    platform_products: str = DEFAULT_PLATFORM_PRODUCTS

    # Swagger UI и схема OpenAPI (/api/platform/docs, /openapi.json). По умолчанию выключены:
    # наружу схема не нужна, а Swagger UI грузит скрипты с CDN и всё равно не проходит CSP шлюза.
    api_docs: bool = False

    manifest_poll_seconds: int = 60
    background_tasks: bool = Field(default=True)

    def product_ids(self) -> list[str]:
        """Все id из PLATFORM_PRODUCTS, в том числе без адреса."""
        return parse_product_ids(self.platform_products)

    def products(self) -> list[ProductConfig]:
        """Подключённые продукты: id из PLATFORM_PRODUCTS с непустым <ID>_API_UPSTREAM."""
        env = _product_env()
        out: list[ProductConfig] = []
        for pos, pid in enumerate(self.product_ids()):
            prefix = pid.upper()
            upstream = env.get(f"{prefix}_API_UPSTREAM", "").strip()
            if upstream:
                out.append(
                    ProductConfig(
                        id=pid,
                        api_upstream=upstream.rstrip("/"),
                        events_secret=env.get(f"{prefix}_EVENTS_SECRET", ""),
                        web_upstream=env.get(f"{prefix}_WEB_UPSTREAM", "").strip().rstrip("/"),
                        position=pos,
                    )
                )
        return out

    def product(self, product_id: str) -> ProductConfig | None:
        return next((p for p in self.products() if p.id == product_id), None)

    def secret_key_bytes(self) -> bytes:
        if not self.platform_secret_key:
            raise RuntimeError("PLATFORM_SECRET_KEY не задан")
        key = base64.b64decode(self.platform_secret_key)
        if len(key) != 32:
            raise RuntimeError("PLATFORM_SECRET_KEY должен быть 32 байта в base64")
        return key


def _product_env() -> dict[str, str]:
    """Переменные продуктов: окружение процесса поверх .env (как у остальных настроек)."""
    file_values = (
        {k: v for k, v in dotenv_values(".env").items() if v is not None} if os.path.exists(".env") else {}
    )
    return {**file_values, **os.environ}


@lru_cache
def get_settings() -> Settings:
    return Settings()
