import type { AdminProduct } from "../api";

/**
 * Матрица ролей по продуктам: строки берутся из манифестов установленных продуктов,
 * так что новый продукт появляется здесь без правки кода (раздел 1а дорожной карты).
 * Общая для шторки пользователя и шторки команды.
 */
export interface RoleMatrixProps {
  products: AdminProduct[];
  value: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
  disabled?: boolean;
  /** Откуда роль пришла помимо своих (например, «из команды Пентест»); такая роль показана отмеченной и не снимается здесь. */
  inheritedFrom?: (productId: string, role: string) => string | null;
}

export function RoleMatrix({ products, value, onChange, disabled, inheritedFrom }: RoleMatrixProps) {
  const toggle = (pid: string, role: string) => {
    const cur = value[pid] ?? [];
    onChange({ ...value, [pid]: cur.includes(role) ? cur.filter((x) => x !== role) : [...cur, role] });
  };
  if (products.length === 0) return <p className="muted">Продукты не установлены.</p>;
  return (
    <>
      {products.map((p) => (
        <fieldset key={p.id} className="card card-pad" style={{ gap: 8 }} disabled={disabled} data-product={p.id}>
          <legend className="kpi-label" style={{ padding: "0 4px" }}>
            {p.title}
          </legend>
          {Object.keys(p.manifest.roles ?? {}).length === 0 && <span className="muted">В манифесте нет ролей</span>}
          {Object.entries(p.manifest.roles ?? {}).map(([role, label]) => {
            const via = (value[p.id] ?? []).includes(role) ? null : (inheritedFrom?.(p.id, role) ?? null);
            return (
              <label key={role} className="checkbox">
                <input
                  type="checkbox"
                  checked={(value[p.id] ?? []).includes(role) || via !== null}
                  disabled={via !== null}
                  onChange={() => toggle(p.id, role)}
                />
                {label}
                {via && <small className="muted">{via}</small>}
                {(p.manifest.admin_roles ?? []).includes(role) && <span className="pill pill-muted">администрирование продукта</span>}
              </label>
            );
          })}
        </fieldset>
      ))}
    </>
  );
}

/** Тело запроса PUT …/roles: все продукты перечислены, чтобы снятые роли тоже ушли. */
export const rolesBody = (products: AdminProduct[], value: Record<string, string[]>) => ({
  products: Object.fromEntries(products.map((p) => [p.id, value[p.id] ?? []])),
});

/** «Сканер: Аудитор, Оператор; Устранение: Инженер» для таблиц. */
export function rolesSummary(products: AdminProduct[], roles: Record<string, string[]>): string {
  return Object.entries(roles)
    .filter(([, list]) => list.length > 0)
    .map(([pid, list]) => {
      const p = products.find((x) => x.id === pid);
      return `${p?.title ?? pid}: ${list.map((r) => p?.manifest.roles?.[r] ?? r).join(", ")}`;
    })
    .join("; ");
}
