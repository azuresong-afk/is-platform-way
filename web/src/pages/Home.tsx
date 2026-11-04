import { Empty, formatDate, iconByName, Loading, PageHead, useAuth, useProject } from "@platform/ui";
import { ArrowRight, FolderKanban, PlugZap, ShieldOff } from "lucide-react";
import { useEffect, useState } from "react";

import type { MyProduct } from "../api";
import { useShell } from "../components/ShellLayout";
import { safeLink, SummaryBody } from "../summaries";

/** Сколько ждать сводку продукта, прежде чем показать «недоступен» (контракт v1.1, п. 10). */
export const SUMMARY_TIMEOUT_MS = 5000;

type SummaryState =
  | { status: "loading" }
  | { status: "ok"; data: Record<string, unknown>; link?: string }
  | { status: "unavailable"; reason: string }
  | { status: "forbidden" }
  | { status: "no-summary" };

export function HomePage() {
  const { projects, products, loaded } = useShell();
  const { projectId } = useProject();
  const auth = useAuth();
  const project = projects.find((p) => p.id === projectId);

  if (!loaded) return <Loading />;

  return (
    <>
      <PageHead breadcrumbs="Платформа" title="Главная" />
      {project ? (
        <section className="card card-pad hero">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 13, flexWrap: "wrap" }}>
            <div>
              <div className="kpi-label">Текущий проект</div>
              <h2 style={{ fontSize: 26 }}>{project.name}</h2>
            </div>
            <span className={`pill ${project.status === "active" ? "pill-ok" : "pill-muted"}`}>
              {project.status === "active" ? "Активный" : "Архив"}
            </span>
          </div>
          <dl className="stat-list" style={{ maxWidth: 560 }}>
            <div>
              <dt>Заказчик</dt>
              <dd>{project.client || "—"}</dd>
            </div>
            <div>
              <dt>Договор</dt>
              <dd>{project.contract_ref || "—"}</dd>
            </div>
            <div>
              <dt>Период работ</dt>
              <dd>
                {project.period_from || project.period_to
                  ? `${formatDate(project.period_from)} — ${formatDate(project.period_to)}`
                  : "не указан"}
              </dd>
            </div>
          </dl>
        </section>
      ) : (
        <section className="card">
          <Empty
            icon={FolderKanban}
            title="Нет доступных проектов"
            text={
              auth.isPlatformAdmin
                ? "Создайте проект и назначьте участников."
                : "Попросите администратора платформы добавить вас в проект."
            }
            action={
              auth.isPlatformAdmin ? (
                <a className="btn btn-primary" href="/admin/projects">
                  Проекты
                </a>
              ) : undefined
            }
          />
        </section>
      )}

      {products.length === 0 ? (
        <section className="card">
          <Empty
            icon={ShieldOff}
            title="Нет доступных продуктов"
            text={
              auth.isPlatformAdmin
                ? "У администратора платформы нет рабочих ролей: их выдаёт другой администратор."
                : "Попросите администратора платформы выдать вам роли в продуктах."
            }
          />
        </section>
      ) : (
        <div className="grid-3">
          {products.map((p) => (
            <ProductCard key={`${p.id}:${projectId}`} product={p} projectId={projectId} />
          ))}
        </div>
      )}
    </>
  );
}

function useSummary(product: MyProduct, projectId: string | null): [SummaryState, () => void] {
  const auth = useAuth();
  const [state, setState] = useState<SummaryState>({ status: "loading" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!product.summary_url) {
      setState({ status: "no-summary" });
      return;
    }
    if (!projectId) return;
    setState({ status: "loading" });
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), SUMMARY_TIMEOUT_MS);
    auth
      .fetch(`${product.summary_url}?project=${encodeURIComponent(projectId)}`, { signal: ctrl.signal, noRedirect: true })
      .then(async (r) => {
        if (r.status === 403) return setState({ status: "forbidden" });
        if (!r.ok) return setState({ status: "unavailable", reason: `ответ ${r.status}` });
        const body = await r.json();
        if (!body || typeof body.data !== "object") return setState({ status: "unavailable", reason: "ответ не по контракту" });
        setState({ status: "ok", data: body.data, link: typeof body.link === "string" ? body.link : undefined });
      })
      .catch(() =>
        setState({ status: "unavailable", reason: ctrl.signal.aborted ? "не ответил вовремя" : "нет связи" }),
      )
      .finally(() => clearTimeout(timer));
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
    // auth.fetch стабилен; перезапрос — по проекту и кнопке «Повторить».
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.summary_url, projectId, tick]);

  return [state, () => setTick((t) => t + 1)];
}

function ProductCard({ product, projectId }: { product: MyProduct; projectId: string | null }) {
  const [state, retry] = useSummary(product, projectId);
  const Icon = iconByName(product.icon);
  const open = `${product.base_path}${projectId ? `?project=${projectId}` : ""}`;

  return (
    <section className="card product-card" data-product={product.id} aria-labelledby={`card-${product.id}`}>
      <div className="card-head">
        <h2 id={`card-${product.id}`}>
          <span className="product-card-icon" aria-hidden="true">
            <Icon size={15} />
          </span>
          {product.title}
        </h2>
        <a className="btn btn-sm btn-ghost" href={state.status === "ok" ? safeLink(state.link, open) : open}>
          Открыть
          <ArrowRight size={15} aria-hidden="true" />
        </a>
      </div>
      <div className="card-pad" style={{ flex: 1 }}>
        {!projectId ? (
          <p className="muted">Выберите проект.</p>
        ) : state.status === "loading" ? (
          <Loading text="Загружаем сводку…" />
        ) : state.status === "unavailable" ? (
          <Empty
            icon={PlugZap}
            title="Недоступен"
            text={`Продукт ${product.title} не ответил: ${state.reason}. Остальные продукты работают.`}
            action={
              <button type="button" className="btn btn-sm" onClick={retry}>
                Повторить
              </button>
            }
          />
        ) : state.status === "forbidden" ? (
          <Empty icon={ShieldOff} title="Нет доступа к проекту" text="В этом продукте у вас нет доступа к выбранному проекту." />
        ) : state.status === "no-summary" ? (
          <p className="muted">Продукт не отдаёт сводку.</p>
        ) : (
          <SummaryBody productId={product.id} data={state.data} />
        )}
      </div>
    </section>
  );
}
