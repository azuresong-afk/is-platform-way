"""Служебные команды platform-api.

    python -m app.cli import-scanner --source postgresql+psycopg://reader:...@scanner-db:5432/scanner
    python -m app.cli import-scanner --source ... --apply --out /tmp/scanner-import

Без --apply ничего не записывается: печатается отчёт о том, что будет сделано.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_settings
from .db import engine_ready, init_engine, session_scope
from .importers import scanner


def _overrides(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in scanner.CANDIDATES or not value:
            raise SystemExit(f"Неверный --map {item!r}; допустимые ключи: {', '.join(scanner.CANDIDATES)}")
        out[key] = value
    return out


def import_scanner(args: argparse.Namespace) -> int:
    report = scanner.Report()
    source = scanner.open_source(args.source)
    try:
        with source.connect() as conn:
            users, engagements = scanner.read_source(conn, _overrides(args.map), report, schema=args.schema)
    except scanner.ImportError_ as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    finally:
        source.dispose()

    if not engine_ready():
        init_engine(get_settings().database_url)
    with session_scope() as db:
        scanner.apply_import(db, users, engagements, report, grant_platform_admin=args.grant_platform_admin)
        if args.apply:
            db.commit()
        else:
            db.rollback()

    print("Столбцы источника:")
    for key, col in report.columns.items():
        print(f"  {key:28} {col or '—'}")
    print("\nИтог" + ("" if args.apply else " (пробный запуск, ничего не записано; добавьте --apply)") + ":")
    for key, value in report.summary().items():
        print(f"  {key:28} {value}")
    if report.scanner_admins:
        print("\nАдминистраторы «Сканера»: " + ", ".join(report.scanner_admins))
        if not args.grant_platform_admin:
            print("  Права администратора платформы не выданы (--grant-platform-admin).")
    if report.users_without_password:
        print("\nБез пароля (задать в «Пользователи»): " + ", ".join(report.users_without_password))
    for name, roles in report.unknown_roles.items():
        print(f"Неизвестные роли у {name}: {', '.join(roles)} — пропущены")
    for warning in report.warnings:
        print("Предупреждение: " + warning)

    if args.apply and args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "mapping.json").write_text(json.dumps(report.mapping, ensure_ascii=False, indent=2), "utf-8")
        (out / "scanner-link-projects.sql").write_text(scanner.scanner_sql(report, engagements), "utf-8")
        print(
            f"\nСоответствия: {out / 'mapping.json'}; SQL для «Сканера»: {out / 'scanner-link-projects.sql'}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-scanner", help="перенос пользователей, ролей и проектов «Сканера»")
    p.add_argument(
        "--source",
        required=True,
        help="URL БД «Сканера» (SQLAlchemy), лучше под пользователем только на чтение",
    )
    p.add_argument("--schema", default=None, help="схема PostgreSQL, если не public")
    p.add_argument(
        "--map", action="append", default=[], metavar="КЛЮЧ=СТОЛБЕЦ", help="явное имя таблицы или столбца"
    )
    p.add_argument("--apply", action="store_true", help="записать изменения (без флага — пробный запуск)")
    p.add_argument(
        "--grant-platform-admin",
        action="store_true",
        help="администраторам «Сканера» дать права администратора платформы",
    )
    p.add_argument("--out", default=None, help="каталог для mapping.json и SQL привязки проектов")
    p.set_defaults(func=import_scanner)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
