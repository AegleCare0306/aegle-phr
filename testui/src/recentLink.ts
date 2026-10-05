/**
 * "A facility was just linked, so records for it are on their way."
 *
 * WHY THIS EXISTS. Linking a care context through UIL does not hand the
 * records back on the spot. ABDM sends the locker an 8.3.11 LINK alert,
 * the locker raises a consent, it auto-approves, the artefact is fetched,
 * a data request goes out and the HIP pushes the bundle back. Measured end
 * to end on 2026-10-03: about seven seconds from link-confirm to a stored,
 * decrypted record.
 *
 * Seven seconds is fast enough to feel immediate -- but only if something
 * is looking. HomeScreen's standing refresh runs every 30 seconds, so
 * without this marker a patient who links a record and goes straight home
 * lands on a screen that reads "no records", with nothing to say more are
 * coming, for up to half a minute. That is indistinguishable from broken,
 * and it is exactly what it was mistaken for.
 *
 * So the UIL screen drops a note here on a successful confirm, and
 * HomeScreen picks it up: poll every few seconds instead of every thirty,
 * and SAY that records are arriving, until they do or the window closes.
 *
 * sessionStorage, not React state or a context: the two screens are
 * separate routes with no shared parent holding this, and the marker must
 * survive the navigation between them. Same storage and the same
 * browser-guard discipline as session.ts, for the same reasons.
 */

const RECENT_LINK_KEY = "aegle.phr.recentLink";

/**
 * How long after a link we keep watching. Generous against the ~7s the
 * chain actually takes, because a slow HIP, a retried push or a gateway
 * hiccup can stretch it -- and bounded, because a link whose records never
 * arrive must stop claiming they are coming and let the normal refresh
 * take over.
 */
export const RECENT_LINK_WINDOW_MS = 120_000;

export interface RecentLink {
  hipId: string;
  hipName: string;
  at: number;
}

function hasBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

/** Called by UilLinkScreen the moment a link is confirmed. */
export function markRecentLink(hipId: string, hipName: string): void {
  if (!hasBrowser() || hipId === "") return;
  try {
    const entry: RecentLink = { hipId, hipName, at: Date.now() };
    window.sessionStorage.setItem(RECENT_LINK_KEY, JSON.stringify(entry));
  } catch {
    // Private mode / blocked storage. The records still arrive and the
    // 30-second refresh still finds them -- the patient just does not get
    // the fast path. Never throw on a successful link because of storage.
  }
}

/**
 * The pending link, or null when there is none or it has aged out.
 *
 * Expiry is evaluated on READ rather than by a timer, so a marker left
 * behind by a closed tab or a slept machine can never cause an old link to
 * be watched forever.
 */
export function getRecentLink(): RecentLink | null {
  if (!hasBrowser()) return null;
  try {
    const raw = window.sessionStorage.getItem(RECENT_LINK_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as Partial<RecentLink>;
    if (typeof parsed.hipId !== "string" || typeof parsed.at !== "number") return null;
    if (Date.now() - parsed.at > RECENT_LINK_WINDOW_MS) {
      clearRecentLink();
      return null;
    }
    return { hipId: parsed.hipId, hipName: typeof parsed.hipName === "string" ? parsed.hipName : parsed.hipId, at: parsed.at };
  } catch {
    return null;
  }
}

/** Called once the expected records land, or when the window closes. */
export function clearRecentLink(): void {
  if (!hasBrowser()) return;
  try {
    window.sessionStorage.removeItem(RECENT_LINK_KEY);
  } catch {
    // Nothing to do -- getRecentLink() expires it on read anyway.
  }
}
