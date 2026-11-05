import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { clearPlatformToken } from "./lib/api";

afterEach(() => {
  cleanup();
  clearPlatformToken();
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
