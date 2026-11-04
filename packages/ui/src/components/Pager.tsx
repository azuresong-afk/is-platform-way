import { ChevronLeft, ChevronRight } from "lucide-react";

import { formatNumber } from "../lib/format";

export interface PagerProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

/** Серверная пагинация: «1–50 из 1 234». */
export function Pager({ total, limit, offset, onChange }: PagerProps) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="pager">
      <span>{`${formatNumber(from)}–${formatNumber(to)} из ${formatNumber(total)}`}</span>
      <div className="pager-buttons">
        <button
          type="button"
          className="btn btn-sm"
          disabled={offset <= 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
          aria-label="Предыдущая страница"
        >
          <ChevronLeft size={15} aria-hidden="true" />
          Назад
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
          aria-label="Следующая страница"
        >
          Вперёд
          <ChevronRight size={15} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
