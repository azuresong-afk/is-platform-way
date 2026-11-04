-- Учебная БД «Сканера» до перехода на платформу (стенд для docs/MIGRATION.md).
-- Схема упрощена: только то, что читает импорт (users, user_permissions, engagements),
-- и прогоны, чтобы было видно, что история «Сканера» при переходе не меняется.
-- Пароли (scrypt, формат «Сканера»): ivanov-pass-1, sidorova-pass-1, petrova-pass-1, scanner-admin-1.

CREATE TABLE users (
    id            serial PRIMARY KEY,
    username      text NOT NULL UNIQUE,
    password_hash text,
    full_name     text,
    email         text,
    is_active     boolean NOT NULL DEFAULT true,
    role          text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_permissions (
    user_id    integer NOT NULL REFERENCES users(id),
    permission text NOT NULL,
    PRIMARY KEY (user_id, permission)
);

CREATE TABLE engagements (
    id           serial PRIMARY KEY,
    name         text NOT NULL,
    client       text,
    contract_ref text,
    status       text NOT NULL DEFAULT 'active',
    created_by   integer REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    id            serial PRIMARY KEY,
    engagement_id integer NOT NULL REFERENCES engagements(id),
    name          text NOT NULL,
    status        text NOT NULL,
    initiated_by  integer REFERENCES users(id),
    finished_at   timestamptz
);

INSERT INTO users (id, username, password_hash, full_name, email, is_active, role) VALUES
 (1, 'ivanov',
  'scrypt$16384$8$1$6976616e6f762d73616c742d30303031$a758052889468949ef2d651e027804cdcee1b729b5df1a26ffc66daae9a398fa9363666c7b9431c1fb78f7bd7edfe2a212aa6e3c0cb370783f7bc88b0ef6dabc',
  'Иванов И. И.', 'ivanov@example.ru', true, 'operator'),
 (2, 'Sidorova',
  'scrypt$16384$8$1$7369646f726f76612d73616c742d3031$ec6ba61ed397a106950224afa653a3d038a1108ab500b2b56d63b55600962bab89e6f42810e17161e5ac8437384375792e3ff6f4e4a0d5e6f2a022e7e3678a40',
  'Сидорова А. А.', NULL, true, 'admin'),
 (3, 'petrova',
  'scrypt$16384$8$1$706574726f76612d73616c742d303031$53a69d2b9577f5ef54162b8fe8886eb3a8640356f62dd90adb214afeaef6d8bd383c7512719da45ab675c3f1bb4df0064566d0ce51b69cd202ad04617a9c49f1',
  'Петрова Е. В.', 'petrova@example.ru', true, 'auditor'),
 (4, 'old', 'bcrypt$2b$12$legacy', 'Уволенный сотрудник', NULL, false, 'operator'),
 (5, 'admin',
  'scrypt$16384$8$1$61646d696e2d73616c742d3030303031$1c76b94735cce491ef1a5aa6e8bf89963446fffca46143e8f5f9ea70ed7e91fc1598d80e13fbe1d7820a96fe8cdb4a7391108edb9501ed2368a8730075e08521',
  'Администратор «Сканера»', NULL, true, 'admin');
SELECT setval('users_id_seq', 5);

INSERT INTO user_permissions VALUES (1, 'host_credentials'), (1, 'cred_audit');

INSERT INTO engagements (id, name, client, contract_ref, status, created_by) VALUES
 (10, 'Пентест ООО Ромашка', 'ООО Ромашка', 'Д-17/2026', 'active', 2),
 (11, 'Аудит банка', 'АО Банк', 'Д-21/2026', 'active', 2),
 (12, 'Пилот 2025', 'ООО Пилот', 'Д-03/2025', 'archived', 5);
SELECT setval('engagements_id_seq', 12);

INSERT INTO runs (engagement_id, name, status, initiated_by, finished_at) VALUES
 (10, 'Первичный прогон', 'done', 1, '2026-10-20T10:00:00Z'),
 (10, 'Повторная проверка', 'partial', 1, '2026-11-03T21:14:00Z'),
 (11, 'Инвентаризация', 'done', 3, '2026-10-28T12:30:00Z');

-- Пользователь только на чтение для утилиты импорта (шаг 2 инструкции).
CREATE ROLE scanner_ro LOGIN PASSWORD 'scanner-ro-pass';
GRANT USAGE ON SCHEMA public TO scanner_ro;
GRANT SELECT ON users, user_permissions, engagements TO scanner_ro;
