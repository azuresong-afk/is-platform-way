import "@testing-library/jest-dom/vitest";
import { clearPlatformToken } from "@platform/ui";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  clearPlatformToken();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});
