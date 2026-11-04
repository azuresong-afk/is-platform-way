/** Русские подписи статусов. */
export const RUN_STATUS: Record<string, { label: string; pill: string }> = {
  pending: { label: "В очереди", pill: "pill-muted" },
  running: { label: "Выполняется", pill: "pill-running" },
  done: { label: "Завершён", pill: "pill-ok" },
  partial: { label: "Частично", pill: "pill-warn" },
  failed: { label: "Ошибка", pill: "pill-danger" },
  stopped: { label: "Остановлен", pill: "pill-muted" },
  interrupted: { label: "Прерван", pill: "pill-warn" },
};

export const HEALTH: Record<string, { label: string; pill: string }> = {
  ok: { label: "Работает", pill: "pill-ok" },
  down: { label: "Недоступен", pill: "pill-danger" },
  unknown: { label: "Нет данных", pill: "pill-muted" },
};

export const PROJECT_STATUS: Record<string, { label: string; pill: string }> = {
  active: { label: "Активный", pill: "pill-ok" },
  archived: { label: "Архив", pill: "pill-muted" },
};

export const DELIVERY_STATUS: Record<string, { label: string; pill: string }> = {
  ok: { label: "Доставлено", pill: "pill-ok" },
  pending: { label: "В очереди", pill: "pill-running" },
  failed: { label: "Повтор", pill: "pill-warn" },
  dead: { label: "Не доставлено", pill: "pill-danger" },
  none: { label: "Нет подписчиков", pill: "pill-muted" },
}

export const KEY_STATUS: Record<string, { label: string; pill: string }> = {
  next: { label: "Опубликован заранее", pill: "pill-info" },
  active: { label: "Подписывает", pill: "pill-ok" },
  retired: { label: "Выведен", pill: "pill-muted" },
  revoked: { label: "Отозван", pill: "pill-danger" },
};
