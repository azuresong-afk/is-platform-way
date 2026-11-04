import { applyStoredTheme, safeNext, setToken, ThemeToggle } from "@platform/ui";
import { Layers3, LogIn } from "lucide-react";
import { type FormEvent, useState } from "react";

import { API } from "../api";

/** Вход: страница в стиле «Сканера», тёмная по умолчанию, возврат на next. */
export function LoginPage() {
  applyStoredTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(typeof body.detail === "string" ? body.detail : "Не удалось войти");
        return;
      }
      setToken(body.access_token);
      const next = new URLSearchParams(window.location.search).get("next");
      window.location.assign(safeNext(next));
    } catch {
      setError("Сервер недоступен. Повторите попытку позже.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="brand">
          <span className="brand-logo" aria-hidden="true">
            <Layers3 size={18} />
          </span>
          <span>
            <div className="brand-title">Платформа</div>
            <div className="brand-subtitle">Единый кабинет продуктов</div>
          </span>
        </div>
        <h1 id="login-title">Вход</h1>
        {error && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">{error}</div>
          </div>
        )}
        <div className="form">
          <label className="field">
            <span>Логин</span>
            <input
              className="input"
              name="username"
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input
              className="input"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <LogIn size={15} aria-hidden="true" />
            {busy ? "Входим…" : "Войти"}
          </button>
        </div>
        <small>Только для авторизованных работ по договору. Действия записываются в журнал аудита.</small>
        <ThemeToggle />
      </form>
    </div>
  );
}
