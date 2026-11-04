import { AlertTriangle, Inbox, type LucideIcon, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

export interface EmptyProps {
  icon?: LucideIcon;
  title: string;
  text?: ReactNode;
  action?: ReactNode;
}

/** Пустое состояние: иконка, заголовок, одна фраза, одна кнопка. */
export function Empty({ icon: Icon = Inbox, title, text, action }: EmptyProps) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">
        <Icon size={22} />
      </div>
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action}
    </div>
  );
}

export function Loading({ text = "Загрузка…" }: { text?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}

export interface ErrorAlertProps {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
}

function message(error: unknown): string {
  if (!error) return "";
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Неизвестная ошибка";
}

export function ErrorAlert({ title = "Не удалось загрузить данные", error, onRetry }: ErrorAlertProps) {
  const text = message(error);
  return (
    <div className="alert-danger" role="alert">
      <AlertTriangle size={18} aria-hidden="true" />
      <div className="alert-body">
        <strong>{title}</strong>
        {text && <span>{text}</span>}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          <RotateCw size={15} aria-hidden="true" />
          Повторить
        </button>
      )}
    </div>
  );
}
