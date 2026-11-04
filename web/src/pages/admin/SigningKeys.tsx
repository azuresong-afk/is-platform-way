import { ConfirmDanger, Empty, ErrorAlert, formatDateTime, Kpi, Loading, Modal, PageHead } from "@platform/ui";
import { KeySquare, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { errorText, get, send, type SigningKey, type SigningKeys } from "../../api";
import { KEY_STATUS } from "../../labels";

// Длинные значения (kid, дата) в карточке KPI не помещаются в 34px.
const SMALL_VALUE = { fontSize: 22 } as const;

/** «1200» → «20 мин», «86400» → «24 ч». */
export function formatSeconds(s: number): string {
  if (s % 86400 === 0) return `${s / 86400} д`;
  if (s % 3600 === 0) return `${s / 3600} ч`;
  if (s % 60 === 0) return `${s / 60} мин`;
  return `${s} с`;
}

function untilText(k: SigningKey): string {
  if (!k.until) return "—";
  if (k.status === "next") return `станет активным ${formatDateTime(k.until)}`;
  if (k.status === "retired") return k.in_jwks ? `в JWKS до ${formatDateTime(k.until)}` : "убран из JWKS";
  return "—";
}

export function SigningKeysPage() {
  const [data, setData] = useState<SigningKeys | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [confirm, setConfirm] = useState<"scheduled" | "immediate" | null>(null);
  const [revoke, setRevoke] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    get<SigningKeys>("/admin/keys").then(setData, setError);
  }, []);
  useEffect(load, [load]);

  const rotate = async (mode: "scheduled" | "immediate") => {
    setBusy(true);
    setMessage(null);
    try {
      const d = await send<SigningKeys>("POST", "/admin/keys/rotate", { mode, revoke_previous: mode === "immediate" && revoke });
      setData(d);
      const lead = formatSeconds(d.schedule.next_lead_seconds);
      setMessage({
        kind: "ok",
        text:
          mode === "scheduled"
            ? `Новый ключ опубликован в JWKS и начнёт подписывать токены через ${lead}.`
            : revoke
              ? "Ключ сменён, прежний отозван: выданные им токены больше не принимаются, пользователи получат новые при обновлении сессии."
              : `Ключ сменён. Прежний остаётся в JWKS ещё ${formatSeconds(d.schedule.jwks_retain_seconds)}.`,
      });
    } catch (e) {
      setMessage({ kind: "danger", text: errorText(e) });
    } finally {
      setBusy(false);
      setConfirm(null);
      setRevoke(false);
    }
  };

  const active = data?.keys.find((k) => k.status === "active");
  const pending = data?.keys.find((k) => k.status === "next");

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Ключи подписи"
        actions={
          <>
            <button type="button" className="btn" onClick={() => setConfirm("scheduled")} disabled={!data || !!pending || busy}>
              <RefreshCw size={15} aria-hidden="true" />
              Плановая смена
            </button>
            <button type="button" className="btn btn-danger" onClick={() => setConfirm("immediate")} disabled={!data || busy}>
              <ShieldAlert size={15} aria-hidden="true" />
              Срочная смена
            </button>
          </>
        }
      />
      <div className="alert-info">
        <div className="alert-body">
          <span>
          Платформа подписывает токены ключом Ed25519, продукты проверяют подпись по{" "}
          <code>/api/platform/.well-known/jwks.json</code> и кэшируют его на 10 минут. При плановой смене новый ключ сначала публикуется в
          JWKS и только потом начинает подписывать, поэтому продукты узнают его заранее. Приватные ключи хранятся зашифрованными и здесь не
          показываются.
          </span>
        </div>
      </div>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      {data?.warnings.map((w) => (
        <div key={w} className="alert-warn" role="alert">
          <div className="alert-body">{w}</div>
        </div>
      ))}
      {data && (
        <div className="kpi-row">
          <Kpi label="Активный ключ" value={<span className="mono" style={SMALL_VALUE}>{active?.kid ?? "—"}</span>} delta={active?.activated_at ? `с ${formatDateTime(active.activated_at)}` : undefined} />
          <Kpi
            label={pending ? "Смена ключа" : "Следующая плановая смена"}
            value={<span style={SMALL_VALUE}>{data.schedule.next_rotation_at ? formatDateTime(data.schedule.next_rotation_at) : "—"}</span>}
            delta={pending ? "новый ключ уже в JWKS" : data.schedule.scheduler_enabled ? undefined : "планировщик выключен"}
            trend={pending ? "good" : data.schedule.scheduler_enabled ? undefined : "bad"}
          />
          <Kpi label="Период ротации" value={`${data.schedule.rotation_days} дн.`} delta={`публикация заранее: ${formatSeconds(data.schedule.next_lead_seconds)}`} />
          <Kpi
            label="Прежний ключ в JWKS"
            value={formatSeconds(data.schedule.jwks_retain_seconds)}
            delta={`срок access-токена: ${formatSeconds(data.schedule.access_ttl_seconds)}`}
          />
        </div>
      )}
      <section className="card">
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !data ? (
          <Loading />
        ) : data.keys.length === 0 ? (
          <Empty icon={KeySquare} title="Ключей нет" text="Ключ создаётся при первом запуске API." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>kid</th>
                  <th>Статус</th>
                  <th>Алгоритм</th>
                  <th>Создан</th>
                  <th>Активирован</th>
                  <th>Выведен</th>
                  <th>JWKS</th>
                </tr>
              </thead>
              <tbody>
                {data.keys.map((k) => {
                  const s = KEY_STATUS[k.status] ?? { label: k.status, pill: "pill-muted" };
                  return (
                    <tr key={k.kid}>
                      <td className="mono">{k.kid}</td>
                      <td>
                        <span className={`pill ${s.pill}`}>{s.label}</span>
                      </td>
                      <td className="mono">
                        {k.alg} / {k.crv}
                      </td>
                      <td>{formatDateTime(k.created_at)}</td>
                      <td>{k.activated_at ? formatDateTime(k.activated_at) : <span className="muted">—</span>}</td>
                      <td>{k.retired_at ? formatDateTime(k.retired_at) : <span className="muted">—</span>}</td>
                      <td>
                        {k.in_jwks ? "опубликован" : <span className="muted">нет</span>}
                        {k.until && (
                          <div>
                            <small className="muted">{untilText(k)}</small>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Modal
        open={confirm === "scheduled"}
        title="Плановая смена ключа"
        onClose={() => setConfirm(null)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setConfirm(null)}>
              Отмена
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => rotate("scheduled")}>
              Опубликовать новый ключ
            </button>
          </>
        }
      >
        <p>
          Новый ключ появится в JWKS сразу, а подписывать токены начнёт через {data ? formatSeconds(data.schedule.next_lead_seconds) : "—"} —
          продукты успеют его закэшировать. Текущий ключ после смены останется в JWKS ещё{" "}
          {data ? formatSeconds(data.schedule.jwks_retain_seconds) : "—"}, выданные токены доживут свой срок. Действие записывается в журнал
          аудита.
        </p>
      </Modal>
      <ConfirmDanger
        open={confirm === "immediate"}
        title="Сменить ключ немедленно?"
        confirmLabel={revoke ? "Сменить и отозвать" : "Сменить сейчас"}
        busy={busy}
        onClose={() => {
          setConfirm(null);
          setRevoke(false);
        }}
        onConfirm={() => rotate("immediate")}
      >
        <p>
          Новый ключ начнёт подписывать сразу{pending ? " (будет активирован уже опубликованный ключ)" : ""}. Продукты, не знающие его,
          перечитают JWKS по неизвестному <code>kid</code>.
        </p>
        <label className="checkbox">
          <input type="checkbox" checked={revoke} onChange={(e) => setRevoke(e.target.checked)} />
          Отозвать текущий ключ сразу — при подозрении на утечку
        </label>
        {revoke && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">
              <span>
              Все выданные access-токены перестанут приниматься, в том числе ваш: оболочка и продукты обновят сессии через refresh. Сервисы
              получат новые токены при следующем запросе к <code>/auth/token</code>.
              </span>
            </div>
          </div>
        )}
      </ConfirmDanger>
    </>
  );
}
