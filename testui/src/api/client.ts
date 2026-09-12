/**
 * THE single HTTP choke point for this harness.
 *
 * HARD RULE: `fetch(` appears nowhere else in src/. Every screen goes
 * through apiRequest(), and therefore every screen gets full
 * request/response visibility in the Console panel for free. That is the
 * entire reason this harness exists -- a screen that calls fetch directly
 * silently opts out of the only thing this app is for.
 *
 * The access key is masked at CAPTURE time, not at render time, so the
 * console store never holds the real value in the first place.
 */

import { getConfig } from "../config";
import { addRecord } from "./consoleStore";
import type { ApiResult, ConsoleRecord, ResultKind } from "./types";

export const ACCESS_KEY_HEADER = "X-Aegle-Key";
export const MASKED_KEY = "••••";

export interface RequestOptions {
  method?: string;
  body?: unknown;
  /**
   * Overrides the stored config. The UI never passes this; it exists so the
   * client can be driven from Node against a running backend without a
   * browser or localStorage.
   */
  config?: { apiBaseUrl: string; apiKey: string };
  signal?: AbortSignal;
}

let counter = 0;

function nextId(): string {
  counter += 1;
  return `${Date.now().toString(36)}-${counter}`;
}

function headersToObject(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((value, name) => {
    out[name] = value;
  });
  return out;
}

/** Parses JSON when possible, falls back to raw text. Never throws. */
async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const config = options.config ?? getConfig();
  const method = options.method ?? "GET";
  const url = `${config.apiBaseUrl}${path}`;
  const startedAt = new Date().toISOString();
  const started = Date.now();

  // ngrok's free plan serves an interstitial warning page to anything that
  // looks like a browser, so a request from the deployed page gets HTML back
  // instead of JSON. This header opts out of it. Harmless when the backend is
  // not behind ngrok. Set here, in the single choke point, so no screen can
  // forget it.
  const requestHeaders: Record<string, string> = {
    [ACCESS_KEY_HEADER]: config.apiKey,
    "ngrok-skip-browser-warning": "true",
  };
  if (options.body !== undefined) requestHeaders["Content-Type"] = "application/json";

  // What goes into the console record -- key masked before it is ever stored.
  const recordedHeaders: Record<string, string> = { ...requestHeaders, [ACCESS_KEY_HEADER]: MASKED_KEY };

  const base = {
    id: nextId(),
    startedAt,
    method,
    url,
    requestHeaders: recordedHeaders,
    requestBody: options.body ?? null,
  };

  const finish = (
    kind: ResultKind,
    status: number | null,
    responseHeaders: Record<string, string> | null,
    responseBody: unknown,
    errorMessage: string | null,
    data: T | null,
  ): ApiResult<T> => {
    const record: ConsoleRecord = {
      ...base,
      durationMs: Date.now() - started,
      status,
      responseHeaders,
      responseBody,
      error: errorMessage,
    };
    addRecord(record);
    return { ok: kind === "success", kind, status, data, errorMessage, record };
  };

  if (config.apiBaseUrl.length === 0) {
    return finish("network-error", null, null, null, "No backend URL configured. Open your link, or set it in Settings.", null);
  }

  let response: Response;
  try {
    const init: RequestInit = { method, headers: requestHeaders };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    if (options.signal !== undefined) init.signal = options.signal;
    response = await fetch(url, init);
  } catch (caught) {
    // fetch() rejects for DNS failure, connection refused, TLS problems and
    // CORS blocks alike -- the browser deliberately does not say which.
    const message = caught instanceof Error ? caught.message : String(caught);
    return finish("network-error", null, null, null, `Could not reach ${url} (${message}). Tunnel down, wrong URL, or blocked by CORS.`, null);
  }

  const responseHeaders = headersToObject(response.headers);
  const responseBody = await readBody(response);

  if (!response.ok) {
    const detail =
      responseBody !== null && typeof responseBody === "object" && "detail" in responseBody
        ? String((responseBody as { detail: unknown }).detail)
        : `HTTP ${response.status}`;
    return finish("http-error", response.status, responseHeaders, responseBody, detail, null);
  }

  return finish("success", response.status, responseHeaders, responseBody, null, responseBody as T);
}
