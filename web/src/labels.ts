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

export const AUDIT_RESULT: Record<string, { label: string; pill: string }> = {
  success: { label: "Успех", pill: "pill-ok" },
  failure: { label: "Ошибка", pill: "pill-warn" },
  denied: { label: "Отказ", pill: "pill-danger" },
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

/** Критичность актива (женский род: «критичность»). */
export const CRITICALITY: Record<string, string> = {
  low: "Низкая",
  medium: "Средняя",
  high: "Высокая",
  critical: "Критическая",
};

/** Поля актива для формы и сообщений. */
export const ASSET_FIELDS: Record<string, string> = {
  hostname: "Имя хоста",
  os_family: "Семейство ОС",
  os: "ОС",
  owner: "Владелец",
  criticality: "Критичность",
  tags: "Теги",
  groups: "Группы",
};
