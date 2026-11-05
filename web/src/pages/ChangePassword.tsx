import { apiJson, applyStoredTheme, PageHead, safeNext, setToken, ThemeToggle, useAuth } from "@platform/ui";
import { KeyRound, Layers3, LogOut } from "lucide-react";
import { type FormEvent, useState } from "react";

import { API, errorText } from "../api";

const MIN_LENGTH = 10;

interface TokenOut {
  access_token: string;
}

/** Поля и отправка смены своего пароля: POST /auth/password, в ответ — новый токен (с ролями). */
function PasswordForm({ submitLabel, onDone }: { submitLabel: string; onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError("Новый пароль и повтор не совпадают");
      return;
    }
    setBusy(true);
    try {
      const out = await apiJson<TokenOut>(`${API}/auth/password`, {
        method: "POST",
        json: { current_password: current, new_password: next },
        noRedirect: true,
      });
      setToken(out.access_token);
      setCurrent("");
      setNext("");
      setRepeat("");
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form" onSubmit={submit} aria-label="Смена пароля">
      {error && (
        <div className="alert-danger" role="alert">
          <div className="alert-body">{error}</div>
        </div>
      )}
      <label className="field">
        <span>Текущий пароль</span>
        <input
          className="input"
          type="password"
          autoComplete="current-password"
          required
          autoFocus
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </label>
      <label className="field">
        <span>Новый пароль</span>
        <input
          className="input"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_LENGTH}
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <small>Не короче {MIN_LENGTH} символов и не совпадает с текущим</small>
      </label>
      <label className="field">
        <span>Повтор нового пароля</span>
        <input
          className="input"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_LENGTH}
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
        />
      </label>
      <button type="submit" className="btn btn-primary" disabled={busy}>
        <KeyRound size={15} aria-hidden="true" />
        {busy ? "Сохраняем…" : submitLabel}
      </button>
    </form>
  );
}

/**
 * Обязательная смена временного пароля (docs/SECURITY.md, п. 6): пароль задал администратор,
 * поэтому до смены в токене нет ролей. Страница вместо оболочки на любом адресе; после смены
 * оболочка открывается на том же адресе (или на next, если сюда увёл продукт).
 */
export function ForcedPasswordPage() {
  applyStoredTheme();
  const auth = useAuth();
  const done = () => {
    const next = new URLSearchParams(window.location.search).get("next");
    if (window.location.pathname === "/password") window.location.assign(safeNext(next));
  };
  return (
    <div className="auth-page">
      <div className="card auth-card" aria-labelledby="password-title">
        <div className="brand">
          <span className="brand-logo" aria-hidden="true">
            <Layers3 size={18} />
          </span>
          <span>
            <div className="brand-title">Платформа</div>
            <div className="brand-subtitle">Единый кабинет продуктов</div>
          </span>
        </div>
        <h1 id="password-title">Задайте свой пароль</h1>
        <div className="alert-info">
          <div className="alert-body">
            {`Пароль для «${auth.user?.username ?? ""}» задал администратор. Продукты откроются, когда вы смените его на свой.`}
          </div>
        </div>
        <PasswordForm submitLabel="Сменить и продолжить" onDone={done} />
        <button type="button" className="btn btn-ghost" onClick={auth.logout}>
          <LogOut size={15} aria-hidden="true" />
          Выйти
        </button>
        <ThemeToggle />
      </div>
    </div>
  );
}

/** Смена пароля из меню пользователя: «Сменить пароль». */
export function PasswordPage() {
  const auth = useAuth();
  const [saved, setSaved] = useState(false);
  const local = auth.claims?.auth_source === "local";
  return (
    <>
      <PageHead breadcrumbs="Профиль" title="Смена пароля" />
      <section className="card card-pad" style={{ maxWidth: 480 }}>
        {!local ? (
          <p className="muted">Пароль внешней учётной записи меняется в её источнике.</p>
        ) : (
          <>
            {saved && (
              <div className="alert-ok" role="status">
                <div className="alert-body">Пароль изменён. Остальные сессии закрыты — на других устройствах войдите заново.</div>
              </div>
            )}
            <PasswordForm submitLabel="Сменить пароль" onDone={() => setSaved(true)} />
          </>
        )}
      </section>
    </>
  );
}
