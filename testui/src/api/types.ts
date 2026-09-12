/**
 * Shapes shared by the HTTP client and the Console panel.
 *
 * Every field on ConsoleRecord is always present. Absent values are `null`,
 * never `undefined` -- a console entry that renders "undefined" is a console
 * entry nobody trusts.
 */

export interface ConsoleRecord {
  id: string;
  startedAt: string;
  durationMs: number;
  method: string;
  url: string;
  requestHeaders: Record<string, string>;
  requestBody: unknown;
  status: number | null;
  responseHeaders: Record<string, string> | null;
  responseBody: unknown;
  error: string | null;
}

export type ResultKind = "success" | "http-error" | "network-error";

export interface ApiResult<T> {
  ok: boolean;
  /**
   * Distinguishes the three outcomes a tester must be able to tell apart:
   *  - success        2xx
   *  - http-error     the server answered, but with 4xx/5xx (e.g. a stale key -> 401)
   *  - network-error  nothing answered (wrong host, tunnel down, CORS blocked)
   */
  kind: ResultKind;
  status: number | null;
  data: T | null;
  errorMessage: string | null;
  record: ConsoleRecord;
}

export interface HealthResponse {
  status: string;
  database: boolean;
}

/**
 * Shape of /phr/aadhaar-enrollment/abha-card -- NOT AbdmPassthrough, since
 * the card is binary (base64-encoded here, not a JSON `body`) with its
 * Content-Type alongside it. See aegle_phr/phr/abha_card.py's own banner.
 */
export interface AbhaCardResponse {
  ok: boolean;
  status: number | null;
  contentType: string | null;
  base64: string | null;
  error: string | null;
}

/**
 * What every enrollment route returns: ABDM's RAW response body under
 * `body`, plus the status our backend saw.
 *
 * `body` is deliberately `unknown`. Three of the five ABDM responses in the
 * registration flow are UNDOCUMENTED — ABDM's spec leaves the Response Body
 * section empty for verify, suggestion and enrol. Declaring a shape here
 * would be inventing one. Screens narrow it defensively at the point of use.
 */
export interface AbdmPassthrough {
  ok: boolean;
  status: number | null;
  body: unknown;
  error: string | null;
  /**
   * Only on /phr/enrollment/address-exists. Mirrors ABDM's bare boolean
   * under an unambiguous name: true = the address is TAKEN, false = free.
   * ABDM's isExists reads backwards from "availability" — confirmed by
   * experiment 2026-08-27.
   */
  taken?: boolean | null;
  /**
   * Only on /phr/aadhaar-enrollment/enrol. Set to a short human string
   * (e.g. "Incorrect OTP.") when ABDM's response matched one of the two
   * confirmed wrong-OTP signatures for that endpoint (tracker case M1-16)
   * -- null on success or on an unrecognised failure, in which case the
   * raw body above is what to look at, not this field.
   */
  knownFailure?: string | null;
  /**
   * Only on /phr/data-flow/request (P10, 2026-09-02). Set to the literal
   * string "consent_not_in_local_cache" when this specific consentId is
   * structurally unusable -- raised by a DIFFERENT app/registration, so
   * repo/'s own local consent cache will never have a row for it, no
   * matter how long a caller waits or retries. A stable, machine-checkable
   * signal alongside the human-readable `error` text above, so
   * HomeScreen.tsx's own self-view coverage logic doesn't need to string-
   * match prose that's free to reword later. null/absent on every other
   * outcome, success included.
   */
  reasonCode?: string | null;
  /**
   * Only on the three User-Initiated Linking outbound routes
   * (/phr/uil/discover, /phr/uil/link-init, /phr/uil/link-confirm, P15).
   * Each of those three returns a bare 202 Accepted with nothing useful in
   * ABDM's own `body` -- this backend-generated REQUEST-ID is what the
   * screen actually needs, to poll GET /phr/uil/result?requestId=... for
   * the real answer once the matching callback arrives. Absent on every
   * other route.
   */
  requestId?: string | null;
}
