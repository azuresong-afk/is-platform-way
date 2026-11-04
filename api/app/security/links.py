"""Ссылки внутри origin платформы: путь возврата, ссылки уведомлений, URL-поля манифеста.

Браузер перед разбором URL выбрасывает табуляцию и переводы строк, а «\\» в пути считает «/».
Поэтому «/\\t/evil.example» превращается в «//evil.example» — ссылку на чужой сайт.
Допускаем только путь от корня без управляющих символов, пробелов и обратной косой черты
(docs/SECURITY.md, п. 9). Та же проверка в @platform/ui — isSafePath.
"""

from __future__ import annotations

import re

_UNSAFE = re.compile(r"[\x00-\x20\x7f\\]")


def is_safe_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and _UNSAFE.search(value) is None
    )
