"""Сводный реестр активов (контракт v1.1, п. 4).

Источники данных:
- события `<продукт>.asset.upserted` / `<продукт>.asset.deleted` от любого подключённого
  продукта (сегодня их шлёт «Сканер»; список продуктов здесь не зашит);
- ручная правка администратора и импорт CSV — источник `platform`.

Правило слияния: поле, заданное вручную (правкой или CSV), попадает в `manual_fields`
и событиями не перетирается. Остальные поля берутся из самого свежего события.
В `sources[]` у каждого продукта хранится, что он знает об активе: внешний id,
когда видел, время последнего события и присланные значения (`values`) — по ним
поле восстанавливается, когда ручное значение сбрасывают.
"""

from __future__ import annotations

import csv
import io
import ipaddress
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, case, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import events
from .db import aware, utcnow
from .models import Asset, Event, Project

log = logging.getLogger(__name__)

PLATFORM = events.PLATFORM
CRITICALITY = ("low", "medium", "high", "critical")
CRITICALITY_RANK = {c: i + 1 for i, c in enumerate(CRITICALITY)}
TEXT_FIELDS = {"hostname": 255, "os_family": 50, "os": 200, "owner": 200}
LIST_FIELDS = ("tags", "groups")
FIELDS = (*TEXT_FIELDS, "criticality", *LIST_FIELDS)
MAX_LIST = 50
MAX_ITEM = 100

CSV_MAX_BYTES = 5 * 1024 * 1024
CSV_MAX_ROWS = 20_000
CSV_MAX_ERRORS = 100

# Заголовки CSV: английские имена полей и русские подписи из интерфейса.
CSV_ALIASES = {
    "address": "address",
    "адрес": "address",
    "ip": "address",
    "hostname": "hostname",
    "имя хоста": "hostname",
    "хост": "hostname",
    "os_family": "os_family",
    "семейство ос": "os_family",
    "os": "os",
    "ос": "os",
    "owner": "owner",
    "владелец": "owner",
    "criticality": "criticality",
    "критичность": "criticality",
    "tags": "tags",
    "теги": "tags",
    "groups": "groups",
    "группы": "groups",
}
CRITICALITY_ALIASES = {
    "низкая": "low",
    "средняя": "medium",
    "высокая": "high",
    "критическая": "critical",
}

_HOST_RE = re.compile(r"^[a-z0-9_]([a-z0-9_.-]{0,253}[a-z0-9_])?$")


# --- нормализация ---------------------------------------------------------------


def normalize_address(value: Any) -> str:
    """IP (v4/v6) в каноническом виде или DNS-имя в нижнем регистре."""
    if not isinstance(value, str):
        raise ValueError("Адрес обязателен")
    s = value.strip().lower().rstrip(".")
    if not s:
        raise ValueError("Адрес обязателен")
    try:
        return str(ipaddress.ip_address(s))
    except ValueError:
        pass
    if len(s) > 255 or not _HOST_RE.match(s):
        raise ValueError("Адрес — IP или имя хоста")
    return s


def clean_value(field: str, value: Any) -> Any:
    """Проверенное значение поля; ValueError — если значение не подходит."""
    if field in TEXT_FIELDS:
        if value is None:
            return ""
        if not isinstance(value, str | int | float):
            raise ValueError(f"{field}: ожидается строка")
        return str(value).strip()[: TEXT_FIELDS[field]]
    if field == "criticality":
        if value is None or value == "":
            return ""
        v = str(value).strip().lower()
        v = CRITICALITY_ALIASES.get(v, v)
        if v not in CRITICALITY:
            raise ValueError("Критичность: low, medium, high или critical")
        return v
    if field in LIST_FIELDS:
        if value is None:
            return []
        if isinstance(value, str):
            value = re.split(r"[;,]", value)
        if not isinstance(value, list):
            raise ValueError(f"{field}: ожидается список")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str | int):
                continue
            s = str(item).strip()[:MAX_ITEM]
            if s and s not in out:
                out.append(s)
        return out[:MAX_LIST]
    raise ValueError(f"Неизвестное поле {field}")


def _stamp(dt: datetime) -> str:
    """Время с фиксированной точностью: строки сравниваются в хронологическом порядке."""
    return aware(dt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- источники и слияние ----------------------------------------------------------


def _source(asset: Asset, product: str) -> dict | None:
    return next((s for s in asset.sources or [] if s.get("product") == product), None)


def _set_source(asset: Asset, entry: dict) -> None:
    # JSON-колонки без MutableList: всегда присваиваем новый список.
    others = [s for s in asset.sources or [] if s.get("product") != entry["product"]]
    asset.sources = sorted([*others, entry], key=lambda s: s["product"])


def _touch_platform_source(asset: Asset) -> None:
    now = _stamp(utcnow())
    prev = _source(asset, PLATFORM) or {}
    _set_source(
        asset,
        {"product": PLATFORM, "external_id": None, "seen_at": now, "event_time": now, **_keep(prev)},
    )


def _keep(prev: dict) -> dict:
    return {"created_at": prev["created_at"]} if "created_at" in prev else {"created_at": _stamp(utcnow())}


def _value_from_sources(asset: Asset, field: str) -> Any:
    """Значение поля из самого свежего источника, который его присылал."""
    best: tuple[str, Any] | None = None
    for s in asset.sources or []:
        vals = s.get("values") or {}
        if field in vals and (best is None or s.get("event_time", "") > best[0]):
            best = (s.get("event_time", ""), vals[field])
    if best is None:
        return [] if field in LIST_FIELDS else ""
    return best[1]


def find(db: Session, project_id: uuid.UUID, address: str) -> Asset | None:
    return db.scalar(select(Asset).where(Asset.project_id == project_id, Asset.address == address))


def _get_or_create(db: Session, project_id: uuid.UUID, address: str) -> tuple[Asset, bool]:
    asset = find(db, project_id, address)
    if asset is not None:
        return asset, False
    asset = Asset(project_id=project_id, address=address, tags=[], groups=[], sources=[], manual_fields=[])
    try:
        with db.begin_nested():
            db.add(asset)
            db.flush()
    except IntegrityError:
        # параллельно создали тот же (project_id, address)
        asset = find(db, project_id, address)
        assert asset is not None
        return asset, False
    return asset, True


def apply_manual(asset: Asset, values: dict[str, Any], reset: list[str] | None = None) -> dict:
    """Ручные значения (правка, CSV). Возвращает {поле: [было, стало]} по изменившимся полям."""
    changes: dict[str, list] = {}
    manual = list(asset.manual_fields or [])
    for field in reset or []:
        if field in manual:
            manual.remove(field)
            new = _value_from_sources(asset, field)
            old = getattr(asset, field)
            if old != new:
                changes[field] = [old, new]
                setattr(asset, field, new)
    for field, value in values.items():
        old = getattr(asset, field)
        if field not in manual:
            manual.append(field)
        if old != value:
            changes[field] = [old, value]
            setattr(asset, field, value)
    if sorted(manual) != sorted(asset.manual_fields or []):
        changes.setdefault("manual_fields", [sorted(asset.manual_fields or []), sorted(manual)])
    asset.manual_fields = sorted(manual)
    _touch_platform_source(asset)
    asset.updated_at = utcnow()
    return changes


# --- события продуктов ------------------------------------------------------------


def _event_kind(event: Event) -> str | None:
    if event.source == PLATFORM:
        return None  # свои platform.asset.* — только для подписчиков
    if event.type == f"{event.source}.asset.upserted":
        return "upserted"
    if event.type == f"{event.source}.asset.deleted":
        return "deleted"
    return None


@events.on("*")
def on_event(db: Session, event: Event) -> None:
    """`<продукт>.asset.upserted|deleted` от любого продукта установки.

    Ошибки в данных не отклоняют событие (повтор доставки их не исправит): событие
    остаётся в журнале шины, реестр не меняется, в лог — только id.
    """
    kind = _event_kind(event)
    if kind is None:
        return
    data = event.data or {}
    if event.project_id is None or db.get(Project, event.project_id) is None:
        log.warning("Событие %s (%s): проект не найден, реестр активов не изменён", event.id, event.type)
        return
    try:
        address = normalize_address(data.get("address"))
    except ValueError:
        log.warning("Событие %s (%s): некорректный адрес, реестр активов не изменён", event.id, event.type)
        return
    if kind == "upserted":
        _upsert(db, event, address, data)
    else:
        _remove_source(db, event, address)


def _upsert(db: Session, event: Event, address: str, data: dict) -> None:
    asset, _ = _get_or_create(db, event.project_id, address)
    prev = _source(asset, event.source)
    etime = _stamp(event.time)
    if prev and prev.get("event_time", "") > etime:
        return  # пришло позже, но устарело: свежие данные уже применены
    values: dict[str, Any] = dict((prev or {}).get("values") or {})
    for field in FIELDS:
        if field not in data:
            continue
        try:
            values[field] = clean_value(field, data[field])
        except ValueError:
            continue
    manual = set(asset.manual_fields or [])
    for field, value in values.items():
        if field not in manual and getattr(asset, field) != value:
            setattr(asset, field, value)
    seen = _parse_time(data.get("last_seen_at")) or event.time
    ext = data.get("asset_id")
    _set_source(
        asset,
        {
            "product": event.source,
            "external_id": str(ext)[:100] if ext not in (None, "") else None,
            "seen_at": _stamp(seen),
            "event_time": etime,
            "values": values,
        },
    )
    asset.updated_at = utcnow()


def _remove_source(db: Session, event: Event, address: str) -> None:
    asset = find(db, event.project_id, address)
    if asset is None:
        return
    prev = _source(asset, event.source)
    if prev is None or prev.get("event_time", "") > _stamp(event.time):
        return
    asset.sources = [s for s in asset.sources or [] if s.get("product") != event.source]
    if not asset.sources and not asset.manual_fields:
        db.delete(asset)
        return
    manual = set(asset.manual_fields or [])
    for field in FIELDS:
        if field not in manual:
            setattr(asset, field, _value_from_sources(asset, field))
    asset.updated_at = utcnow()


# --- CSV ------------------------------------------------------------------------


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Файл не в UTF-8 и не в Windows-1251")


def import_csv(db: Session, project_id: uuid.UUID, raw: bytes) -> dict:
    """Импорт CSV: значения из файла становятся ручными. Пустая ячейка поле не меняет.

    Коммит — на стороне вызывающего. ValueError — файл целиком не подходит.
    """
    if len(raw) > CSV_MAX_BYTES:
        raise ValueError("Файл больше 5 МБ")
    text = _decode(raw)
    if not text.strip():
        raise ValueError("Файл пустой")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None) or []
    columns: list[str | None] = [CSV_ALIASES.get(h.strip().lower()) for h in header]
    if "address" not in columns:
        raise ValueError("Нет колонки address (адрес)")
    report: dict[str, Any] = {
        "rows": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "errors": [],
        "error_count": 0,
    }

    def error(line: int, text_: str) -> None:
        report["error_count"] += 1
        if len(report["errors"]) < CSV_MAX_ERRORS:
            report["errors"].append({"line": line, "error": text_})

    for row in reader:
        line = reader.line_num
        if not any(c.strip() for c in row):
            continue
        report["rows"] += 1
        if report["rows"] > CSV_MAX_ROWS:
            raise ValueError(f"Больше {CSV_MAX_ROWS} строк — разделите файл")
        cells = {col: row[i] for i, col in enumerate(columns) if col and i < len(row)}
        try:
            address = normalize_address(cells.pop("address", ""))
            values = {f: clean_value(f, v) for f, v in cells.items() if v.strip()}
        except ValueError as exc:
            error(line, str(exc))
            continue
        asset, created = _get_or_create(db, project_id, address)
        changes = apply_manual(asset, values)
        if created:
            report["created"] += 1
        elif changes:
            report["updated"] += 1
        else:
            report["unchanged"] += 1
    return report


# --- чтение -----------------------------------------------------------------------


def _array_has(db: Session, column, value: str):
    if db.get_bind().dialect.name == "postgresql":
        return column.op("@>")(literal([value], JSONB))
    je = func.json_each(column).table_valued("value")
    return exists(select(literal(1)).select_from(je).where(je.c.value == value))


def _source_has(db: Session, product: str):
    if db.get_bind().dialect.name == "postgresql":
        return Asset.sources.op("@>")(literal([{"product": product}], JSONB))
    je = func.json_each(Asset.sources).table_valued("value")
    return exists(
        select(literal(1)).select_from(je).where(func.json_extract(je.c.value, "$.product") == product)
    )


def _like(q: str) -> str:
    return "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


SORTS = {
    "address": Asset.address,
    "hostname": Asset.hostname,
    "owner": Asset.owner,
    "updated_at": Asset.updated_at,
    "criticality": case(CRITICALITY_RANK, value=Asset.criticality, else_=0),
}


def query(
    db: Session,
    project_id: uuid.UUID,
    *,
    q: str | None = None,
    criticality: list[str] | None = None,
    os_family: str | None = None,
    owner: str | None = None,
    tag: str | None = None,
    group: str | None = None,
    source: str | None = None,
    manual: bool | None = None,
    updated_since: datetime | None = None,
    sort: str = "address",
) -> Select:
    stmt = select(Asset).where(Asset.project_id == project_id)
    if q:
        like = _like(q)
        stmt = stmt.where(
            or_(
                *(
                    func.lower(c).like(like, escape="\\")
                    for c in (Asset.address, Asset.hostname, Asset.owner, Asset.os)
                )
            )
        )
    if criticality:
        stmt = stmt.where(Asset.criticality.in_(["" if c == "none" else c for c in criticality]))
    if os_family:
        stmt = stmt.where(func.lower(Asset.os_family) == os_family.lower())
    if owner:
        stmt = stmt.where(func.lower(Asset.owner) == owner.lower())
    if tag:
        stmt = stmt.where(_array_has(db, Asset.tags, tag))
    if group:
        stmt = stmt.where(_array_has(db, Asset.groups, group))
    if source:
        stmt = stmt.where(_source_has(db, source))
    if manual is not None:
        has_manual = _array_has_any(db)
        stmt = stmt.where(has_manual if manual else ~has_manual)
    if updated_since:
        stmt = stmt.where(Asset.updated_at >= updated_since)
    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"), Asset.address)
    stmt = stmt.order_by(col.desc() if desc else col.asc(), Asset.address, Asset.id)
    return stmt


def _array_has_any(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return func.jsonb_array_length(Asset.manual_fields) > 0
    return func.json_array_length(Asset.manual_fields) > 0


def asset_out(a: Asset) -> dict:
    return {
        "id": str(a.id),
        "project_id": str(a.project_id),
        "address": a.address,
        "hostname": a.hostname,
        "os_family": a.os_family,
        "os": a.os,
        "owner": a.owner,
        "criticality": a.criticality or None,
        "tags": list(a.tags or []),
        "groups": list(a.groups or []),
        "sources": [{k: s.get(k) for k in ("product", "external_id", "seen_at")} for s in a.sources or []],
        "manual_fields": list(a.manual_fields or []),
        "created_at": aware(a.created_at).isoformat(),
        "updated_at": aware(a.updated_at).isoformat(),
    }


def facets(db: Session, project_id: uuid.UUID) -> dict:
    """Значения для фильтров: теги, группы, семейства ОС, источники (по проекту)."""
    tags: set[str] = set()
    groups: set[str] = set()
    sources: set[str] = set()
    fams: set[str] = set()
    rows = db.execute(
        select(Asset.tags, Asset.groups, Asset.sources, Asset.os_family).where(Asset.project_id == project_id)
    )
    for t, g, s, f in rows:
        tags.update(t or [])
        groups.update(g or [])
        sources.update(x.get("product") for x in s or [] if x.get("product"))
        if f:
            fams.add(f)
    return {
        "tags": sorted(tags),
        "groups": sorted(groups),
        "sources": sorted(sources),
        "os_families": sorted(fams),
    }
