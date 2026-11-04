/**
 * Страж стиля «Сканера» (критерий приёмки «неотличимы по стилю»): дизайн-токены styles.css совпадают
 * с разделом «Дизайн-токены» задания docs/spec/03-platforma.md дословно. Единственное допустимое отличие —
 * угловатое оформление по решению владельца (контракт v1.1, п. 9.1).
 */
/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

import specMd from "../../../docs/spec/03-platforma.md?raw";
import stylesCss from "./styles.css?raw";

const APPROVED: Record<string, string> = { "--radius": "4px", "--radius-sm": "3px" };

/** Токены первых блоков `:root` и `:root[data-theme="light"]` (без медиазапросов). */
function tokens(css: string): Record<string, Record<string, string>> {
  const out: Record<string, Record<string, string>> = {};
  for (const sel of [":root", ':root[data-theme="light"]']) {
    const start = css.indexOf(`${sel} {`);
    expect(start, `нет блока ${sel}`).toBeGreaterThanOrEqual(0);
    const body = css.slice(start, css.indexOf("}", start));
    out[sel] = Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  }
  return out;
}

describe("дизайн-токены", () => {
  it("совпадают с заданием, кроме утверждённого скругления", () => {
    const spec = tokens(specMd);
    const ours = tokens(stylesCss);
    for (const sel of Object.keys(spec)) {
      const expected = { ...spec[sel], ...(sel === ":root" ? APPROVED : {}) };
      expect(ours[sel], sel).toEqual(expected);
    }
  });
});
