/**
 * Runtime configuration: the backend URL and the shared access key.
 *
 * Both arrive as query parameters the first time a tester opens their link:
 *
 *   https://<app>.vercel.app/?api=https://<ngrok-host>&key=<shared-key>
 *
 * They are saved to localStorage and then STRIPPED from the address bar, so
 * a screenshot or a shared tab does not leak the key. On later visits the
 * stored values are used and the plain URL works.
 *
 * Nothing here is baked into the build -- no VITE_* default, no value in
 * source. Anything compiled into a Vercel bundle is public.
 *
 * Every window/localStorage access is guarded so this module can be imported
 * outside a browser (e.g. driving client.ts from Node).
 */

const API_STORAGE_KEY = "aegle.phr.apiBaseUrl";
const KEY_STORAGE_KEY = "aegle.phr.apiKey";

export interface AppConfig {
  apiBaseUrl: string;
  apiKey: string;
}

function hasBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readStored(name: string): string {
  if (!hasBrowser()) return "";
  try {
    return window.localStorage.getItem(name) ?? "";
  } catch {
    // Private mode / blocked storage: fall back to an empty value rather
    // than throwing during first render.
    return "";
  }
}

function writeStored(name: string, value: string): void {
  if (!hasBrowser()) return;
  try {
    window.localStorage.setItem(name, value);
  } catch {
    /* ignore -- the settings panel still works for this session */
  }
}

/** Trailing slashes make `${base}${path}` produce a double slash. */
function normaliseBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "");
}

/**
 * Reads ?api= and ?key= (if present), persists them, and removes them from
 * the address bar. Safe to call more than once. Call once on startup,
 * before anything reads the config.
 */
export function consumeUrlParameters(): void {
  if (!hasBrowser()) return;

  const url = new URL(window.location.href);
  const apiParam = url.searchParams.get("api");
  const keyParam = url.searchParams.get("key");

  if (apiParam === null && keyParam === null) return;

  if (apiParam !== null) writeStored(API_STORAGE_KEY, normaliseBaseUrl(apiParam));
  if (keyParam !== null) writeStored(KEY_STORAGE_KEY, keyParam.trim());

  url.searchParams.delete("api");
  url.searchParams.delete("key");

  // replaceState, not pushState: the link with the key must not sit in
  // browser history where it can be recovered with the Back button.
  const cleaned = url.pathname + (url.searchParams.toString() ? `?${url.searchParams}` : "") + url.hash;
  window.history.replaceState({}, "", cleaned);
}

export function getConfig(): AppConfig {
  return {
    apiBaseUrl: readStored(API_STORAGE_KEY),
    apiKey: readStored(KEY_STORAGE_KEY),
  };
}

export function setConfig(next: AppConfig): void {
  writeStored(API_STORAGE_KEY, normaliseBaseUrl(next.apiBaseUrl));
  writeStored(KEY_STORAGE_KEY, next.apiKey.trim());
}

export function isConfigured(config: AppConfig): boolean {
  return config.apiBaseUrl.length > 0 && config.apiKey.length > 0;
}
