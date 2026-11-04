"""Перенос пользователей и проектов «Сканера» (шаг 2.1)."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import create_engine, select, text

from app.cli import main as cli_main
from app.importers import scanner
from app.models import AuditLog, Project, ProjectLink, ProjectMember, User
from tests.helpers import login


def scanner_hash(password: str) -> str:
    salt = b"s" * 16
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


@pytest.fixture
def source_url(tmp_path):
    """БД «Сканера»: роль столбцом, надбавки отдельной таблицей."""
    url = f"sqlite:///{tmp_path / 'scanner.sqlite3'}"
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(
            text(
                "create table users (id integer primary key, username text, password_hash text, "
                "full_name text, email text, is_active boolean, role text)"
            )
        )
        c.execute(text("create table user_permissions (user_id integer, permission text)"))
        c.execute(
            text(
                "create table engagements (id integer primary key, name text, client text, "
                "contract_ref text, created_at text)"
            )
        )
        rows = [
            (1, "Ivanov", scanner_hash("ivanov-pass-1"), "Иванов И. И.", "iv@example.ru", True, "operator"),
            (2, "sidorova", scanner_hash("sid-pass-12"), "Сидорова А. А.", None, True, "admin"),
            (3, "old", "bcrypt$whatever", "Бывший", None, False, "auditor,superuser"),
            (4, "admin", scanner_hash("x-pass-123"), "Админ Сканера", None, True, "admin"),
        ]
        for r in rows:
            c.execute(
                text("insert into users values (:i,:u,:p,:n,:e,:a,:r)"),
                dict(zip("iupnear", r, strict=True)),
            )
        c.execute(text("insert into user_permissions values (1, 'host_credentials'), (1, 'cred_audit')"))
        c.execute(
            text(
                "insert into engagements values"
                " (10, 'Пентест ООО Ромашка', 'ООО Ромашка', 'Д-17/2026', '2026-01-01'),"
                " (11, 'Аудит банка', 'АО Банк', 'Д-21/2026', '2026-02-01')"
            )
        )
    eng.dispose()
    return url


def run(source_url, db, **kw):
    report = scanner.Report()
    src = scanner.open_source(source_url)
    with src.connect() as conn:
        users, engs = scanner.read_source(conn, {}, report)
    src.dispose()
    scanner.apply_import(db, users, engs, report, **kw)
    db.commit()
    return report, users, engs


def test_import_users_roles_projects(client, db, source_url):
    report, _, engs = run(source_url, db)
    assert report.columns["users.display_name"] == "full_name"
    assert report.columns["roles.table"] == "user_permissions"
    assert sorted(report.users_created) == ["ivanov", "old", "sidorova"]
    # bootstrap-админ платформы уже есть: ему только добавляется роль «Сканера»
    assert report.users_updated == ["admin"]
    assert report.unknown_roles == {"old": ["superuser"]}
    assert report.users_without_password == ["old"]
    assert sorted(report.scanner_admins) == ["admin", "sidorova"]

    iv = db.scalar(select(User).where(User.username == "ivanov"))
    assert {r.role for r in iv.roles if r.product_id == "scanner"} == {
        "operator",
        "host_credentials",
        "cred_audit",
    }
    assert iv.all_projects and iv.display_name == "Иванов И. И." and not iv.is_platform_admin
    old = db.scalar(select(User).where(User.username == "old"))
    assert not old.is_active and old.password_hash is None
    sid = db.scalar(select(User).where(User.username == "sidorova"))
    assert not sid.is_platform_admin  # без --grant-platform-admin

    projects = {p.name: p for p in db.scalars(select(Project)).all()}
    assert projects["Пентест ООО Ромашка"].contract_ref == "Д-17/2026"
    links = {link.external_id: link.project_id for link in db.scalars(select(ProjectLink)).all()}
    assert links == {"10": projects["Пентест ООО Ромашка"].id, "11": projects["Аудит банка"].id}

    # существующий пользователь без «всех проектов» получил участие в перенесённых
    admin = db.scalar(select(User).where(User.username == "admin"))
    if not admin.all_projects:
        members = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == admin.id)))
        assert members == set(links.values())

    assert db.scalar(select(AuditLog).where(AuditLog.action == "import.scanner")) is not None

    sql = scanner.scanner_sql(report, engs)
    assert f'UPDATE "engagements" SET platform_project_id = \'{links["10"]}\' WHERE "id" = 10;' in sql


def test_scanner_password_works_after_import(client, db, source_url):
    run(source_url, db)
    token, _ = login(client, "Ivanov", "ivanov-pass-1")
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert "operator" in me["products"]["scanner"]


def test_import_is_idempotent(client, db, source_url):
    run(source_url, db)
    users_before = db.scalar(select(text("count(*)")).select_from(User))
    report, _, _ = run(source_url, db)
    assert report.users_created == [] and report.projects_created == []
    assert sorted(report.users_unchanged) == ["admin", "ivanov", "old", "sidorova"]
    assert sorted(report.projects_existing) == ["Аудит банка", "Пентест ООО Ромашка"]
    assert db.scalar(select(text("count(*)")).select_from(User)) == users_before
    assert len(db.scalars(select(Project)).all()) == 2


def test_rerun_syncs_revoked_role_and_keeps_password(client, db, source_url):
    run(source_url, db)
    iv = db.scalar(select(User).where(User.username == "ivanov"))
    iv.password_hash = "scrypt$changed"
    db.commit()
    eng = create_engine(source_url)
    with eng.begin() as c:
        c.execute(text("delete from user_permissions where permission = 'cred_audit'"))
    eng.dispose()
    report, _, _ = run(source_url, db)
    assert "ivanov" in report.users_updated
    db.refresh(iv)
    assert {r.role for r in iv.roles if r.product_id == "scanner"} == {"operator", "host_credentials"}
    assert iv.password_hash == "scrypt$changed"


def test_grant_platform_admin(client, db, source_url):
    run(source_url, db, grant_platform_admin=True)
    assert db.scalar(select(User).where(User.username == "sidorova")).is_platform_admin
    assert not db.scalar(select(User).where(User.username == "ivanov")).is_platform_admin


def test_alternative_schema_and_map(client, db, tmp_path):
    url = f"sqlite:///{tmp_path / 'alt.sqlite3'}"
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(
            text(
                "create table accounts (uid text primary key, login text, hashed_password text,"
                " disabled boolean, roles text)"
            )
        )
        c.execute(
            text("create table engagement (id text primary key, title text, customer text, status text)")
        )
        c.execute(
            text("insert into accounts values ('u1', 'petrov', :h, 0, :r)"),
            {"h": scanner_hash("p-pass-123"), "r": json.dumps(["auditor", "cred_audit"])},
        )
        c.execute(text("insert into engagement values ('e-1', 'Старый', 'Заказчик', 'archived')"))
    eng.dispose()

    report = scanner.Report()
    src = scanner.open_source(url)
    with src.connect() as conn:
        users, engs = scanner.read_source(conn, {"users.id": "uid"}, report)
    src.dispose()
    scanner.apply_import(db, users, engs, report)
    db.commit()

    petrov = db.scalar(select(User).where(User.username == "petrov"))
    assert petrov.is_active
    assert {r.role for r in petrov.roles} == {"auditor", "cred_audit"}
    project = db.scalar(select(Project).where(Project.name == "Старый"))
    assert project.status == "archived" and project.client == "Заказчик"
    assert "WHERE \"id\" = 'e-1'" in scanner.scanner_sql(report, engs)


def test_missing_users_table_is_reported(tmp_path):
    url = f"sqlite:///{tmp_path / 'empty.sqlite3'}"
    src = scanner.open_source(url)
    with src.connect() as conn, pytest.raises(scanner.ImportError_):
        scanner.read_source(conn, {}, scanner.Report())


def test_cli_dry_run_writes_nothing(client, db, source_url, tmp_path, capsys):
    assert cli_main(["import-scanner", "--source", source_url]) == 0
    printed = capsys.readouterr().out
    assert "пробный запуск" in printed
    # логин «admin» уже занят администратором платформы — оператор должен это увидеть до --apply
    assert (
        "Уже есть в платформе, получат роли «Сканера» (пароль и профиль платформы не меняются): admin"
        in printed
    )
    db.expire_all()
    assert db.scalar(select(User).where(User.username == "ivanov")) is None

    out = tmp_path / "out"
    assert cli_main(["import-scanner", "--source", source_url, "--apply", "--out", str(out)]) == 0
    db.expire_all()
    assert db.scalar(select(User).where(User.username == "ivanov")) is not None
    mapping = json.loads((out / "mapping.json").read_text("utf-8"))
    assert set(mapping["engagements"]) == {"10", "11"}
    assert "platform_project_id" in (out / "scanner-link-projects.sql").read_text("utf-8")


def test_cli_rejects_bad_map(source_url):
    with pytest.raises(SystemExit):
        cli_main(["import-scanner", "--source", source_url, "--map", "users.nope=x"])
