/**
 * Global light/dark theme toggle for the Aegle Care palette (2026-09-07 --
 * Quicksand: gold #CB9C30 / green #154541 / white #DFDED1, see styles.css's
 * own token block banner for the full palette story).
 *
 * Same shape as rawVisibility.ts: a tiny subscribe/emit store, persisted to
 * localStorage with the same guarded pattern as config.ts, so a choice
 * survives a reload. Applied by setting `data-theme` on <html>, which is
 * what styles.css's `[data-theme="dark"]` token overrides key off.
 *
 * No stored preference yet -- first run falls back to the OS's own
 * prefers-color-scheme, same three-state logic Artifacts use: explicit
 * choice beats system, system is the default until the user picks.
 */

export type Theme = "light" | "dark";

const STORAGE_KEY = "aegle.phr.theme";

function hasBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readStored(): Theme | null {
  if (!hasBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : null;
  } catch {
    return null;
  }
}

function writeStored(value: Theme): void {
  if (!hasBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* ignore -- the toggle still works for this render, just won't persist */
  }
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyToDocument(value: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", value);
}

let theme: Theme = readStored() ?? (systemPrefersDark() ? "dark" : "light");
applyToDocument(theme);

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function getTheme(): Theme {
  return theme;
}

export function setTheme(value: Theme): void {
  theme = value;
  writeStored(value);
  applyToDocument(value);
  emit();
}

export function toggleTheme(): void {
  setTheme(theme === "dark" ? "light" : "dark");
}

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
