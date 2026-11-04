import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Radar } from "lucide-react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
  ErrorAlert,
  formatDateTime,
  formatNumber,
  formatPercent,
  Layout,
  Modal,
  Pager,
  ProductTabs,
  ProjectPicker,
  QuickSearch,
  SeverityBadge,
  ThemeToggle,
  useProject,
  useTheme,
  withProject,
} from "./index";

const P1 = "11111111-1111-4111-8111-111111111111";
const P2 = "22222222-2222-4222-8222-222222222222";

describe("форматирование", () => {
  it("дата, числа, проценты по-русски", () => {
    expect(formatDateTime(new Date(2026, 10, 4, 16, 54))).toBe("04.11.2026 16:54");
    expect(formatNumber(1234567)).toBe("1 234 567");
    expect(formatPercent(42)).toBe("42 %");
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("useTheme", () => {
  it("по умолчанию тёмная, читает старый ключ «Сканера»", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
    window.localStorage.setItem("scanner.theme", "light");
    const second = renderHook(() => useTheme());
    expect(second.result.current.theme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("platform.theme важнее scanner.theme и переключается", () => {
    window.localStorage.setItem("scanner.theme", "light");
    window.localStorage.setItem("platform.theme", "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
    act(() => result.current.toggle());
    expect(window.localStorage.getItem("platform.theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("слушает смену темы в другом продукте (событие storage)", () => {
    const { result } = renderHook(() => useTheme());
    act(() => {
      window.localStorage.setItem("platform.theme", "light");
      window.dispatchEvent(new StorageEvent("storage", { key: "platform.theme" }));
    });
    expect(result.current.theme).toBe("light");
  });

  it("кнопка подписана по-русски", async () => {
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Светлая тема" }));
    expect(screen.getByRole("button", { name: "Тёмная тема" })).toBeInTheDocument();
  });
});

describe("useProject", () => {
  it("?project= в адресе важнее сохранённого и запоминается", () => {
    window.localStorage.setItem("platform.project", P1);
    window.history.replaceState(null, "", `/scanner/runs?project=${P2}`);
    const { result } = renderHook(() => useProject());
    expect(result.current.projectId).toBe(P2);
    expect(window.localStorage.getItem("platform.project")).toBe(P2);
  });

  it("смена проекта пишет localStorage и адрес", () => {
    window.history.replaceState(null, "", "/vm/queue?status=open");
    const { result } = renderHook(() => useProject());
    act(() => result.current.setProject(P1));
    expect(window.location.search).toBe(`?status=open&project=${P1}`);
    expect(window.localStorage.getItem("platform.project")).toBe(P1);
    expect(result.current.withProject("/grc/")).toBe(`/grc/?project=${P1}`);
  });

  it("мусор в адресе игнорируется", () => {
    window.history.replaceState(null, "", "/?project=<script>");
    const { result } = renderHook(() => useProject());
    expect(result.current.projectId).toBeNull();
  });

  it("withProject заменяет параметр и сохраняет якорь", () => {
    expect(withProject(`/a?project=${P1}&x=1#h`, P2)).toBe(`/a?project=${P2}&x=1#h`);
    expect(withProject("/a", null)).toBe("/a");
  });
});

describe("компоненты", () => {
  it("SeverityBadge — подпись уровня", () => {
    render(<SeverityBadge level="critical" />);
    expect(screen.getByText("Критический")).toHaveClass("sev", "sev-critical");
  });

  it("Pager", async () => {
    const onChange = vi.fn();
    const { container } = render(<Pager total={1234} limit={50} offset={50} onChange={onChange} />);
    expect(container.querySelector(".pager span")?.textContent).toBe("51–100 из 1\u00a0234");
    await userEvent.click(screen.getByRole("button", { name: "Следующая страница" }));
    expect(onChange).toHaveBeenCalledWith(100);
    await userEvent.click(screen.getByRole("button", { name: "Предыдущая страница" }));
    expect(onChange).toHaveBeenCalledWith(0);
  });

  it("Modal закрывается по Esc", () => {
    const onClose = vi.fn();
    render(
      <Modal open title="Удалить проект" onClose={onClose}>
        текст
      </Modal>,
    );
    expect(screen.getByRole("dialog", { name: "Удалить проект" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("ErrorAlert с кнопкой «Повторить»", async () => {
    const retry = vi.fn();
    render(<ErrorAlert error={new Error("Сервер недоступен")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Сервер недоступен");
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(retry).toHaveBeenCalled();
  });

  it("ProjectPicker: select без подписи с aria-label и архивом", async () => {
    const onChange = vi.fn();
    render(
      <ProjectPicker
        projects={[
          { id: P1, name: "Ромашка" },
          { id: P2, name: "Старый", status: "archived" },
        ]}
        value={P1}
        onChange={onChange}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Проект" });
    expect(select).toHaveValue(P1);
    await userEvent.selectOptions(select, P2);
    expect(onChange).toHaveBeenCalledWith(P2);
    expect(screen.getByRole("group", { name: "Архив" })).toBeInTheDocument();
  });

  it("ProductTabs: Главная + продукты, ссылки несут проект", () => {
    render(
      <ProductTabs
        active="vm"
        projectId={P1}
        products={[
          { id: "scanner", title: "Сканер", icon: "radar", base_path: "/scanner/" },
          { id: "vm", title: "Устранение", icon: "wrench", base_path: "/vm/" },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Продукты" });
    const links = Array.from(nav.querySelectorAll("a"));
    expect(links.map((a) => a.textContent)).toEqual(["Главная", "Сканер", "Устранение"]);
    expect(links[1]).toHaveAttribute("href", `/scanner/?project=${P1}`);
    expect(links[2]).toHaveAttribute("aria-current", "page");
  });

  it("Layout рисует строку вкладок только в режиме платформы", () => {
    const props = {
      brand: { title: "Сканер", subtitle: "уязвимости", icon: Radar },
      nav: [{ to: "/", label: "Сводка", icon: Radar, end: true }],
      adminNav: [{ to: "/users", label: "Пользователи", icon: Radar }],
      user: { name: "Иванов Иван", roles: ["Оператор"] },
      tabs: <div data-testid="tabs" />,
    };
    const { rerender } = render(
      <MemoryRouter>
        <Layout {...props}>контент</Layout>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("tabs")).toBeNull();
    expect(screen.getByText("Администрирование")).toBeInTheDocument();
    expect(screen.getByText("ИИ")).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <Layout {...props} platform>
          контент
        </Layout>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("tabs")).toBeInTheDocument();
  });
});

describe("QuickSearch", () => {
  it("Ctrl+K, параллельный поиск, группировка и таймаут медленного источника", async () => {
    const onNavigate = vi.fn();
    const fast = {
      id: "scanner",
      title: "Сканер",
      search: vi.fn(async () => [{ title: "CVE-2024-6387", subtitle: "10.0.0.5", link: "/scanner/f/1", severity: "critical" }]),
    };
    const slow = {
      id: "vm",
      title: "Устранение",
      search: (_q: string, signal: AbortSignal) =>
        new Promise<never>((_r, reject) => signal.addEventListener("abort", () => reject(new Error("abort")))),
    };
    const broken = { id: "grc", title: "Аттестация", search: async () => Promise.reject(new Error("500")) };
    render(
      <QuickSearch
        sources={[fast, slow, broken]}
        commands={[{ id: "go-vm", label: "Перейти в Устранение", href: "/vm/" }]}
        timeoutMs={300}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox", { name: "Строка поиска" });
    await userEvent.type(input, "openssh");
    expect(await screen.findByText("CVE-2024-6387")).toBeInTheDocument();
    expect(await screen.findByText("Недоступен")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Не ответил вовремя")).toBeInTheDocument(), { timeout: 2000 });
    expect(fast.search).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("/scanner/f/1");
  });

  it("команды «Перейти в…» фильтруются по вводу", async () => {
    const onNavigate = vi.fn();
    render(
      <QuickSearch
        commands={[
          { id: "a", label: "Перейти в Сканер", href: "/scanner/" },
          { id: "b", label: "Перейти в Аттестацию", href: "/grc/" },
        ]}
        onNavigate={onNavigate}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Быстрый поиск" }));
    const input = await screen.findByRole("combobox", { name: "Строка поиска" });
    await userEvent.type(input, "атт");
    expect(screen.queryByText("Перейти в Сканер")).toBeNull();
    await userEvent.click(screen.getByText("Перейти в Аттестацию"));
    expect(onNavigate).toHaveBeenCalledWith("/grc/");
  });
});
