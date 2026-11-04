"""Настройки platform-api из переменных окружения (.env)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Идентификаторы продуктов по контракту v1, п. 1.
PRODUCT_IDS = ("scanner", "vm", "grc")


@dataclass(frozen=True)
class ProductConfig:
    id: str
    # Внутренний адрес API продукта (без /api/<id>), например http://scanner-app:8000
    api_upstream: str
    events_secret: str


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

    # Продукты установки: пустой адрес — продукта нет.
    scanner_api_upstream: str = ""
    vm_api_upstream: str = ""
    grc_api_upstream: str = ""
    scanner_events_secret: str = ""
    vm_events_secret: str = ""
    grc_events_secret: str = ""

    manifest_poll_seconds: int = 60
    background_tasks: bool = Field(default=True)

    def products(self) -> list[ProductConfig]:
        out: list[ProductConfig] = []
        for pid in PRODUCT_IDS:
            upstream = getattr(self, f"{pid}_api_upstream").strip()
            if upstream:
                out.append(
                    ProductConfig(
                        id=pid,
                        api_upstream=upstream.rstrip("/"),
                        events_secret=getattr(self, f"{pid}_events_secret"),
                    )
                )
        return out

    def secret_key_bytes(self) -> bytes:
        if not self.platform_secret_key:
            raise RuntimeError("PLATFORM_SECRET_KEY не задан")
        key = base64.b64decode(self.platform_secret_key)
        if len(key) != 32:
            raise RuntimeError("PLATFORM_SECRET_KEY должен быть 32 байта в base64")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
