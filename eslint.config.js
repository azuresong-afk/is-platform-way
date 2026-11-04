import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["**/dist/**", "**/dist-showcase/**", "**/node_modules/**", "**/coverage/**", "api/**", "dev/**", "e2e/playwright-report/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Данные выводятся только как текст или в <iframe sandbox>.",
        },
      ],
    },
  },
  {
    files: ["**/*.config.{js,ts}", "**/scripts/**/*.{js,mjs}"],
    languageOptions: { globals: { ...globals.node } },
  },
);
