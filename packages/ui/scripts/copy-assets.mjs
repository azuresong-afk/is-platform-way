// Копирует styles.css и шрифты в dist: шрифты — отдельными файлами dist/fonts/*.woff2,
// чтобы сборщик продукта выложил их рядом со своими ассетами (CSP разрешает шрифты только с 'self').
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const dist = join(root, "dist");
const require = createRequire(import.meta.url);
mkdirSync(join(dist, "fonts"), { recursive: true });

const fontsSrc = readFileSync(join(root, "src", "fonts.css"), "utf8");
const imports = [...fontsSrc.matchAll(/@import "(@fontsource\/[^"]+)";/g)].map((m) => m[1]);
let out = "/* Шрифты Inter и JetBrains Mono (локально, OFL-1.1). */\n";
for (const spec of imports) {
  const cssPath = require.resolve(spec);
  let css = readFileSync(cssPath, "utf8");
  // Оставляем только woff2: все поддерживаемые браузеры его читают.
  css = css.replace(/,\s*url\([^)]+\.woff\) format\('woff'\)/g, "");
  css = css.replace(/url\(\.\/files\/([^)]+\.woff2)\)/g, (_m, file) => {
    copyFileSync(join(dirname(cssPath), "files", file), join(dist, "fonts", file));
    return `url(./fonts/${file})`;
  });
  out += css + "\n";
}
writeFileSync(join(dist, "fonts.css"), out);
copyFileSync(join(root, "src", "styles.css"), join(dist, "styles.css"));
console.log(`@platform/ui: styles.css и ${imports.length} начертаний шрифтов скопированы в dist/`);
