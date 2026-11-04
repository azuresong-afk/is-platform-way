/** Ключи хранилища браузера по контракту v1.1, п. 11. */
export const TOKEN_KEY = "platform.token";
export const PROJECT_KEY = "platform.project";
export const THEME_KEY = "platform.theme";
/** Прежний ключ темы «Сканера» — читается, если platform.theme ещё не задан. */
export const LEGACY_THEME_KEY = "scanner.theme";

export function safeGet(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

export function safeSet(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    /* приватный режим или запрет хранилища — работаем без него */
  }
}

export const local = () => window.localStorage;
export const session = () => window.sessionStorage;
