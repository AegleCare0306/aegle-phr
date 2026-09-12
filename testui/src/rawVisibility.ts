/**
 * Global, live-toggleable switch for every inline "raw ABDM response"
 * block across the app (RawBody, components/RawBody.tsx) -- Aayush's
 * explicit request: OFF hides every one of them, ON shows every one of
 * them, switchable mid-flow with no reload and no redoing any step.
 *
 * NOT the Console panel (api/consoleStore.ts) -- that already starts each
 * entry collapsed and is this harness's own dedicated, always-available
 * debug drawer, unaffected by this toggle. This is specifically about the
 * ALWAYS-RENDERED inline blocks that clutter each screen's own
 * step-by-step view when left on.
 *
 * Persisted to localStorage (same guarded pattern as config.ts) so a
 * debugging session survives a reload. A tiny subscribe/emit store (same
 * shape as api/consoleStore.ts) is what makes every RawBody instance
 * across every screen re-render the instant the toggle flips, without
 * threading a prop through six separate files -- consolidating those six
 * previously-duplicated RawBody copies into one shared component
 * (components/RawBody.tsx) is what makes "no exceptions" actually
 * enforceable, rather than trusting six separate edits to stay in sync.
 */

const STORAGE_KEY = "aegle.phr.showRawResponses";

function hasBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readStored(): boolean {
  if (!hasBrowser()) return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeStored(value: boolean): void {
  if (!hasBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    /* ignore -- the toggle still works for this render, just won't persist */
  }
}

let showRaw = readStored();
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function getShowRawResponses(): boolean {
  return showRaw;
}

export function setShowRawResponses(value: boolean): void {
  showRaw = value;
  writeStored(value);
  emit();
}

export function subscribeShowRawResponses(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
