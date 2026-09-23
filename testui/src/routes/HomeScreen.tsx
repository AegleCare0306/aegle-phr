/**
 * Post-login landing page (Aayush's explicit request) -- every login
 * screen (PasswordLoginScreen/MobileLoginScreen/OtpLoginScreen) navigates
 * here immediately on a successful login, instead of showing its own
 * inline "Logged in as ..." view. Photo, ABHA Number, ABHA Address, and
 * Linked Records -- the full profile view/edit/link-management stays
 * exactly where it was (ProfileScreen.tsx, unchanged), reachable from
 * the nav.
 *
 * PHOTO -- SAME CAVEAT AS ProfileScreen.tsx: Get Profile carries no photo
 * field in either the spec's own example or a real saved Postman example
 * -- see that screen's own banner. This page makes the same defensive
 * check and shows the same "no photo available" note when absent, rather
 * than fabricating a placeholder.
 *
 * LINKED RECORDS ("Get All Linked Records" chunk): HIP-Initiated
 * Linking's OWN view (spec section 9 -- care contexts a HIP already
 * linked to this ABHA address); User-Initiated Linking (discovering/
 * linking NEW records, spec section 10) is a separate, later chunk, not
 * part of this page. RESPONSE SHAPE CONFIRMED LIVE against SS9.3.5's own
 * `patient.links[]` shape -- see aegle_phr/phr/links.py for the full
 * SS6.12-vs-SS9.3.5 story this settled.
 *
 * THREE-LEVEL DRILL-DOWN (redesigned 2026-09-01, replacing an earlier
 * flat expand/collapse, per Aayush's own reference screenshots of a real
 * PHR app -- "the requests are grouped by [facility], then when I click
 * view details it lists consents..., ... it is not just displayed for
 * the sake of displaying"): mirrors ConsentScreen.tsx's own established
 * Level 1/2/3 pattern for consistency across the app.
 *   Level 1 -- one card per HIP (groupByHip(), unchanged from before).
 *   Level 2 -- tap a facility: the individual linked records under it
 *   (one per §9.3.5 `links[]` entry), each with "View Details" and
 *   "Pull Records".
 *   Level 3 -- tap "View Details" on one record: the actual decrypted
 *   clinical content for it (Diagnosis/Medications/Vitals/
 *   Investigations/...), parsed from the FHIR bundle Data Flow (spec §7)
 *   retrieves -- see the FHIR-rendering section below.
 *
 * DATA FLOW (spec §7) LIVES HERE NOW, NOT IN CONSENT MANAGER -- MOVED
 * 2026-09-01 on Aayush's own direction: pulling a record belongs next to
 * the record, not in a separate consent admin screen. "Pull Records" on a
 * facility fetches its care contexts' actual clinical content, and Level 3
 * renders the decrypted FHIR bundle.
 *
 * WHERE THE CONTENT COMES FROM (rewritten in P19). Everything shown here
 * is data OUR OWN HEALTH LOCKER fetched for this patient, and nothing
 * else. The locker holds a subscription for the patient, so ABDM alerts it
 * whenever a care context is linked or updated; the backend raises a
 * consent as the locker and the locker's own auto-approval policy grants
 * it. By the time this screen renders, the consents it can pull under are
 * exactly the ones our locker raised -- extractCoveringConsents() enforces
 * that with a single check, consentDetail.hiu.id === our locker id.
 *
 * WHAT P19 DELETED FROM THIS FILE, and why none of it is missed:
 *   - the self-view auto-provisioning effect, which spotted an uncovered
 *     HIP, raised a PATRQT self-view consent for it, and polled ABDM for
 *     that request to be granted;
 *   - SelfViewWaitingCallout, which narrated those phases to the patient;
 *   - knownBadConsentIds and its localStorage persistence, which
 *     remembered consent ids that could never be pulled;
 *   - three fire-and-forget login calls (discoverSelfViewConsents,
 *     ensureSelfSubscription, ensureSelfViewAutoApprove).
 * All of it existed to work around one problem: a PATRQT consent raised by
 * THIS app was indistinguishable from a PATRQT self-grant belonging to a
 * DIFFERENT app, so the screen had to guess, try, fail, and remember. With
 * the locker there is an unambiguous owner on every consent, so the guess
 * -- and everything built to survive guessing wrong -- is gone. The
 * patient is no longer asked to wait for, or approve, anything here.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import {
  ArrowLeft,
  Building2,
  Calendar,
  ClipboardList,
  Download,
  Eye,
  FileText,
  FlaskConical,
  Home,
  IdCard,
  Inbox,
  Loader2,
  Pill,
  RefreshCw,
  Search,
  Stethoscope,
  Syringe,
  UserRound,
} from "lucide-react";

import {
  getAllConsentArtefacts,
  getLockerRecords,
  getLockerStatus,
  getAllLinkedRecords,
  getHealthInformationStatus,
  getProfile,
  requestHealthInformation,
  triggerConsentFetch,
} from "../api/endpoints";
import type { LockerRecord, LockerStatus } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card, CardBody, CardFooter, CardTitle } from "../components/ui/Card";
import { CardGrid } from "../components/ui/CardGrid";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoRow } from "../components/ui/InfoRow";
import { ListRow } from "../components/ui/ListRow";
import { PageHeader } from "../components/ui/PageHeader";
import { ProfileHeader } from "../components/ui/ProfileHeader";
import { getSessionAddress, getSessionToken } from "../session";

function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

function objField(body: unknown, key: string): Record<string, unknown> {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (value !== null && typeof value === "object") return value as Record<string, unknown>;
  }
  return {};
}

/** Same as objField(), but for a value already in hand rather than a key to look up on a parent object -- used throughout the FHIR parsing below, where a resource's own field is already an arbitrary unknown value. */
function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * P14 (2026-09-03) -- persisted, not just in-memory. CONFIRMED LIVE: some
 * of a patient's self-view grants point at care contexts from old/
 * regenerated test data the HIP no longer has -- a pull for one of those
 * can NEVER succeed, no matter how long it's given. knownBadConsentIds
 * (extractCoveringConsents()'s own banner) already existed as REACT STATE,
 * which resets on every fresh page load -- so a dead consent got a brand
 * new pullRecords() attempt (and a brand-new backend request) EVERY
 * reload, forever, since autoFetchTriggeredRef is also in-memory-only and
 * offers no protection across reloads either. Persisting to localStorage
 * closes that: once something has been given a fair, generous chance (see
 * pollStatus()'s own POLL_MAX_ATTEMPTS x POLL_INTERVAL_MS budget) and
 * still never arrived, it stays excluded on every future visit too --
 * extractCoveringConsents() moves on to a different candidate for that
 * HIP instead (several usually exist), rather than this app hammering the
 * same dead one forever. Same guarded-localStorage pattern as config.ts.
 */
function formatDate(iso: string): string {
  if (iso === "") return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }).replace(/ /g, "-");
}

// --- Level 1/2: Linked Records (spec §9.3.5) -----------------------------

interface LinkedCareContext {
  referenceNumber: string;
  display: string;
}

interface LinkedRecord {
  hipName: string;
  hipId: string;
  referenceNumber: string;
  display: string;
  hiType: string;
  careContexts: LinkedCareContext[];
  dateCreated: string;
}

/**
 * Reads spec SS9.3.5's own documented shape ({patient: {links: [...]}}) --
 * the one links.py's own module banner trusts over the contradicting
 * SS6.12 example. Returns null (not an empty array) when the shape
 * doesn't match at all, so the caller can tell "no records" apart from
 * "this isn't the shape we expected" and fall back to the raw dump.
 */
function extractLinkedRecords(body: unknown): LinkedRecord[] | null {
  if (body === null || typeof body !== "object" || !("patient" in body)) return null;
  const patient = (body as { patient: unknown }).patient;
  if (patient === null || typeof patient !== "object" || !("links" in patient)) return null;
  const links = (patient as { links: unknown }).links;
  if (!Array.isArray(links)) return null;

  const records: LinkedRecord[] = [];
  for (const item of links) {
    if (item === null || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const hipObj = objField(record, "hip");
    const rawCareContexts = record.careContexts;
    const careContexts: LinkedCareContext[] = Array.isArray(rawCareContexts)
      ? rawCareContexts
          .filter((cc): cc is Record<string, unknown> => cc !== null && typeof cc === "object")
          .map((cc) => ({
            referenceNumber: typeof cc.referenceNumber === "string" ? cc.referenceNumber : "",
            display: typeof cc.display === "string" ? cc.display : "",
          }))
      : [];
    records.push({
      hipName: typeof hipObj.name === "string" ? hipObj.name : "",
      hipId: typeof hipObj.id === "string" ? hipObj.id : "",
      referenceNumber: typeof record.referenceNumber === "string" ? record.referenceNumber : "",
      display: typeof record.display === "string" ? record.display : "",
      hiType: typeof record.hiType === "string" ? record.hiType : "",
      careContexts,
      dateCreated: typeof record.dateCreated === "string" ? record.dateCreated : "",
    });
  }
  return records;
}

interface HipGroup {
  /** hipId when present (stable even if a HIP's display name is blank/changes), else the name, else a literal fallback -- always non-empty, safe as a React key. */
  key: string;
  label: string;
  records: LinkedRecord[];
}

/**
 * One visible record row -- one per ACTUAL care context, never per raw
 * ABDM link object. `parent` carries the link-level fields (hipId,
 * hiType, dateCreated, etc.) this specific care context doesn't have its
 * own copy of.
 */
interface FlatRecordRow {
  parent: LinkedRecord;
  careContext: LinkedCareContext;
}

/**
 * Flattens LinkedRecord[] (one entry per raw ABDM `patient.links[]`
 * object) into one row per individual care context. FIXED (2026-09-05,
 * real bug found live): a single ABDM link object can bundle SEVERAL
 * care contexts at once (confirmed live -- MS Hospital returned one
 * Prescription link object covering 2 genuinely different clinical
 * records, "Pulmonary Tuberculosis" and "Distal Radius Fracture", linked
 * in the same batch) -- rendering one card per raw link object (the old
 * behavior) made those two show up as ONE indistinguishable card instead
 * of two separate ones, even though they're unrelated records with their
 * own distinct content. Flattening here means the visible record count
 * always matches the actual number of linkable care contexts, regardless
 * of how ABDM happened to batch them. A link entry with zero care
 * contexts (shouldn't normally happen) still gets exactly one row, using
 * the link's own top-level referenceNumber/display as a fallback, so it
 * isn't silently dropped.
 */
function flattenToCareContextRows(records: LinkedRecord[]): FlatRecordRow[] {
  const rows: FlatRecordRow[] = [];
  for (const record of records) {
    if (record.careContexts.length === 0) {
      rows.push({ parent: record, careContext: { referenceNumber: record.referenceNumber, display: record.display } });
    } else {
      for (const cc of record.careContexts) {
        rows.push({ parent: record, careContext: cc });
      }
    }
  }
  return rows;
}

/** Collapses per-entry records into one group per HIP -- see this file's own banner for why. */
function groupByHip(records: LinkedRecord[]): HipGroup[] {
  const groups = new Map<string, HipGroup>();
  for (const record of records) {
    const key = record.hipId || record.hipName || "unknown-hip";
    const label = record.hipName || record.hipId || "Unknown HIP";
    const existing = groups.get(key);
    if (existing) {
      existing.records.push(record);
    } else {
      groups.set(key, { key, label, records: [record] });
    }
  }
  return Array.from(groups.values());
}

// --- Data Flow (spec §7): the consent that covers each HIP --------------

interface CoveringConsent {
  consentId: string;
  hipId: string;
  hiuId: string;
  periodFrom: string;
  periodTo: string;
}

/**
 * Which GRANTED consents cover each HIP, so "Pull Records" has something
 * to pull under. Returns every usable candidate per HIP, not just one --
 * a single HIP can have SEVERAL granted artefacts at once (confirmed live:
 * one covering all four of a patient's linked care contexts at a facility,
 * plus three narrower ones each covering a single context). Each ABDM
 * data-flow request only ever returns what ITS OWN consent covers and
 * there is no call that unions coverage, so the only way to see everything
 * is to pull from every candidate and merge -- see pullRecords().
 *
 * REWRITTEN IN P19, and much simpler than what it replaced. The old
 * version had to guess: it filtered on purpose.code === "PATRQT" plus a
 * requester.name check plus a reactive knownBadConsentIds set persisted in
 * localStorage, all because self-view consents raised by THIS app were
 * genuinely indistinguishable from PATRQT self-grants belonging to a
 * DIFFERENT app (ABDM's own sandbox PHR self-grants on every link), and
 * the only way to tell them apart was to try one and watch it fail.
 *
 * With the Health Locker there is an unambiguous discriminator:
 * consentDetail.hiu.id. A consent our locker raised carries our locker's
 * id; nobody else's does. That is the same rule the backend enforces
 * (locker_service._is_ours()), so the two agree by construction rather
 * than by two different heuristics happening to line up. No purpose
 * sniffing, no requester-name matching, no known-bad list.
 *
 * Same defensive wrapped-or-flat consentDetail handling as
 * ConsentScreen.tsx's own extractArtefactItem(), duplicated here per this
 * codebase's own per-screen-helper convention.
 */
function extractCoveringConsents(body: unknown, lockerId: string): Map<string, CoveringConsent[]> {
  const map = new Map<string, CoveringConsent[]>();
  if (lockerId === "") return map;
  if (body === null || typeof body !== "object" || !("consentArtefacts" in body)) return map;
  const artefacts = (body as { consentArtefacts: unknown }).consentArtefacts;
  if (!Array.isArray(artefacts)) return map;

  for (const item of artefacts) {
    if (item === null || typeof item !== "object") continue;
    if (stringField(item, "status").toUpperCase() !== "GRANTED") continue;
    const wrapped = objField(item, "consentDetail");
    const detail = Object.keys(wrapped).length > 0 ? wrapped : (item as Record<string, unknown>);

    // THE one check that matters: did OUR locker raise this?
    const hiu = objField(detail, "hiu");
    if (hiu.id !== lockerId) continue;

    const hip = objField(detail, "hip");
    const permission = objField(detail, "permission");
    const dateRange = objField(permission, "dateRange");
    const hipId = typeof hip.id === "string" ? hip.id : "";
    if (hipId === "") continue;
    const consentId = typeof detail.consentId === "string"
      ? detail.consentId
      : typeof detail.requestId === "string" ? detail.requestId : "";
    if (consentId === "") continue;

    const candidate: CoveringConsent = {
      consentId,
      hipId,
      hiuId: typeof hiu.id === "string" ? hiu.id : "",
      periodFrom: typeof dateRange.from === "string" ? dateRange.from : "",
      periodTo: typeof dateRange.to === "string" ? dateRange.to : "",
    };
    const existing = map.get(hipId);
    if (existing) existing.push(candidate);
    else map.set(hipId, [candidate]);
  }

  return map;
}

// --- Data Flow (spec §7): pulling + the per-HIP poll state --------------

interface PulledCareContext {
  hiStatus: string;
  description: string;
  bundle: unknown;
}

/**
 * One covering consent's own independent pull progress. REWRITTEN
 * (2026-09-05, alongside extractCoveringConsents()'s own fix -- see that
 * function's banner) from a single flat PullState per HIP into one of
 * these PER covering consent, because a HIP can now have more than one
 * usable covering consent at once and each is pulled independently (its
 * own request/poll cycle, its own requestId) -- see pullRecords()'s own
 * comment for why they can't be merged into one request.
 */
interface ConsentPullState {
  consentId: string;
  busy: boolean;
  timedOut: boolean;
  requestResult: ApiResult<AbdmPassthrough> | null;
  statusResult: ApiResult<AbdmPassthrough> | null;
  careContexts: Record<string, PulledCareContext> | null;
  /** P12 -- 0 when not in this phase; while > 0, which attempt (1-based) of the trigger-fetch-then-retry loop is in flight, for pullPhaseMessage() below. */
  fetchTriggerAttempt: number;
  /** The requestId this consent's own in-flight/last pull got back -- needed so "Check again" can resume polling THIS consent specifically after a timeout, without touching any other consent's own pull for the same HIP. */
  requestId: string;
}

/**
 * One HIP's own pull state -- now a LIST of independent ConsentPullState
 * entries (one per usable covering consent for this HIP), not a single
 * flat result. mergedCareContexts()/isPullBusy()/isPullTimedOut() below
 * derive the aggregate view the rendering code actually needs (e.g. "are
 * ANY of this HIP's consents still busy") without flattening the
 * underlying per-consent detail away -- see pullRecords()'s own comment
 * for why keeping them separate (rather than combining into one request)
 * is what actually fixes the "only 1 of 4 linked records visible" bug.
 */
interface PullState {
  noConsent: boolean;
  consents: ConsentPullState[];
}

const EMPTY_PULL_STATE: PullState = {
  noConsent: false,
  consents: [],
};

function emptyConsentPullState(consentId: string): ConsentPullState {
  return {
    consentId,
    busy: false,
    timedOut: false,
    requestResult: null,
    statusResult: null,
    careContexts: null,
    fetchTriggerAttempt: 0,
    requestId: "",
  };
}

/** Combines every covering consent's own pulled care contexts into one map for display -- each consent covers a DIFFERENT subset of this HIP's linked care contexts (ABDM never grants overlapping self-view artefacts for the same care context), so a plain merge is safe: nothing here overwrites another consent's own entries. Returns null only when NOT ONE consent has produced anything yet, so "nothing pulled" and "some still pending" stay distinguishable via isPullBusy()/isPullTimedOut() rather than both looking like a plain empty result. */
function mergedCareContexts(pullState: PullState): Record<string, PulledCareContext> | null {
  const withData = pullState.consents.filter((c) => c.careContexts !== null);
  if (withData.length === 0) return null;
  const merged: Record<string, PulledCareContext> = {};
  for (const c of withData) Object.assign(merged, c.careContexts);
  return merged;
}

/**
 * P20 -- builds the per-HIP display state from what the LOCKER ALREADY
 * HOLDS, so a login shows records immediately instead of firing a data
 * request per hospital and waiting for each one.
 *
 * This is the whole point of being a Health Locker rather than a proxy.
 * The locker collects each care context once, when it becomes available
 * (an 8.3.11 alert, or the one-off backfill), and is entitled to keep it
 * for the life of the consent behind it. So a login reads storage.
 *
 * Deliberately produces the SAME PullState shape the on-demand pull
 * produces, rather than a parallel path: every rendering branch,
 * expand/collapse and bundle viewer below keeps working untouched, and
 * "pull records" stays available as a manual refresh. busy/timedOut are
 * false because nothing is in flight -- this data is already here.
 */
function pullStateFromLockerRecords(records: LockerRecord[]): Record<string, PullState> {
  const byHip: Record<string, Record<string, ConsentPullState>> = {};

  for (const record of records) {
    const hipId = record.hipId ?? "";
    if (hipId === "" || record.bundle == null) continue;
    const consentId = record.consentId ?? "locker";

    const consents = (byHip[hipId] ??= {});
    const entry = (consents[consentId] ??= {
      ...emptyConsentPullState(consentId),
      careContexts: {},
    });
    (entry.careContexts as Record<string, PulledCareContext>)[record.careContextReference] = {
      hiStatus: "OK",
      description: "Held by your health locker",
      bundle: record.bundle,
    };
  }

  const result: Record<string, PullState> = {};
  for (const [hipId, consents] of Object.entries(byHip)) {
    result[hipId] = { noConsent: false, consents: Object.values(consents) };
  }
  return result;
}

/**
 * How often the Home screen re-reads the locker.
 *
 * BACKFILL_POLL_MS is fast because the patient is actively waiting on a
 * first-ever login and the screen is visibly incomplete until it lands.
 * RECORDS_POLL_MS is slow because nothing is pending -- it exists only to
 * catch a record that arrived on its own while the app was open, and the
 * focus listener alongside it catches the common case far sooner than any
 * interval would. Both hit a local database read, never ABDM.
 */
const BACKFILL_POLL_MS = 4000;
const RECORDS_POLL_MS = 30000;

function isPullBusy(pullState: PullState): boolean {
  return pullState.consents.some((c) => c.busy);
}

function isPullTimedOut(pullState: PullState): boolean {
  return pullState.consents.some((c) => c.timedOut);
}

const POLL_INTERVAL_MS = 3000;
/**
 * 30 attempts × 3s = 90s total -- a short, bounded wait with a clear
 * timeout message, not an infinite loop. Matches
 * tools/m3_test_suite/common.py's own wait_for_callback() default
 * (timeout=90) -- confirmed live, 2026-09-01: a real pull against a
 * genuinely slower/less-reliable HIP ("MS Hospital") got the on-request
 * ack fine (transaction_id assigned, confirmed in repo/'s own storage)
 * but the data push itself hadn't landed by 60s, this screen's own
 * earlier budget -- undersized against the CLI's own tuned figure. Note
 * the CLI actually budgets 90s for EACH step separately (ack, then push)
 * -- up to 180s worst case -- but this screen polls one merged status
 * covering both steps at once, so 90s here is a floor, not a guarantee;
 * see "Check again" below for what happens past it.
 */
const POLL_MAX_ATTEMPTS = 30;

/**
 * P12 -- bounded retry budget for the "trigger fetch_consent() ourselves,
 * then retry the pull" recovery path (see pullRecords()'s own comment
 * for the full story: ABDM's own HIU-notify callback, confirmed live,
 * never fires for a self-requested/PATRQT consent, so the automatic
 * fetch_consent() trigger that normally happens for a third-party
 * consent never happens here either -- this is what supplies it
 * manually). 5 attempts x 3s = 15s -- generous above the ~0.3-0.6s an
 * on-init ack was observed taking for the SAME account/purpose, since
 * this is one additional real round trip (our own explicit fetch call,
 * then waiting for ITS OWN on-fetch callback) beyond that.
 */
const FETCH_TRIGGER_RETRY_INTERVAL_MS = 3000;
const FETCH_TRIGGER_MAX_ATTEMPTS = 5;

/** data_flow.py's own {phase, transactionId, careContexts} body -- careContexts is null until phase is "complete", not an error, just not there yet. */
function extractPulledCareContexts(body: unknown): Record<string, PulledCareContext> | null {
  if (body === null || typeof body !== "object" || !("careContexts" in body)) return null;
  const raw = (body as Record<string, unknown>).careContexts;
  if (raw === null || typeof raw !== "object") return null;
  const out: Record<string, PulledCareContext> = {};
  for (const [reference, value] of Object.entries(raw as Record<string, unknown>)) {
    if (value === null || typeof value !== "object") continue;
    const record = value as Record<string, unknown>;
    out[reference] = {
      hiStatus: typeof record.hi_status === "string" ? record.hi_status : "",
      description: typeof record.description === "string" ? record.description : "",
      bundle: record.bundle ?? null,
    };
  }
  return out;
}

/** A live, phase-aware "what's actually happening right now" message while a pull is in flight -- so the wait doesn't read as a static, unchanging spinner for up to 90 seconds. Summarizes across every still-busy consent for this HIP now (there can be more than one in flight at once, see PullState's own banner), not just a single one. */
function pullPhaseMessage(pullState: PullState): string {
  const active = pullState.consents.filter((c) => c.busy);
  if (active.length === 0) return "Requesting…";
  if (active.some((c) => c.fetchTriggerAttempt > 0)) return "First time viewing this facility's records — fetching your access details…";
  const phases = active.map((c) => stringField(c.statusResult?.data?.body, "phase"));
  if (phases.every((p) => p === "transaction_assigned")) return "Facility acknowledged the request — waiting for it to push the actual records…";
  if (phases.some((p) => p === "pending")) return "Waiting for the facility to acknowledge the request…";
  return active.length > 1 ? `Requesting from ${active.length} granted access records…` : "Requesting…";
}

/** Wraps an in-memory value (not a fresh network call) as an ApiResult so it can go through the shared RawBody component -- the `url` field says plainly where it actually came from. */
function wrapAsResult(value: unknown, from: string): ApiResult<AbdmPassthrough> {
  return {
    ok: true,
    kind: "success",
    status: 200,
    data: { ok: true, status: 200, body: value, error: null },
    errorMessage: null,
    record: {
      id: "local", startedAt: "", durationMs: 0, method: "GET", url: from,
      requestHeaders: {}, requestBody: null, status: 200, responseHeaders: null, responseBody: value, error: null,
    },
  };
}

// --- FHIR bundle rendering, grounded in repo/'s own real captured data ---

interface FhirEntry {
  resourceType: string;
  resource: Record<string, unknown>;
}

function extractBundleEntries(bundle: unknown): FhirEntry[] {
  if (bundle === null || typeof bundle !== "object" || !("entry" in bundle)) return [];
  const entries = (bundle as Record<string, unknown>).entry;
  if (!Array.isArray(entries)) return [];
  const out: FhirEntry[] = [];
  for (const e of entries) {
    if (e === null || typeof e !== "object") continue;
    const resource = (e as Record<string, unknown>).resource;
    if (resource === null || typeof resource !== "object") continue;
    const resourceType = (resource as Record<string, unknown>).resourceType;
    if (typeof resourceType !== "string") continue;
    out.push({ resourceType, resource: resource as Record<string, unknown> });
  }
  return out;
}

function byType(entries: FhirEntry[], resourceType: string): Record<string, unknown>[] {
  return entries.filter((e) => e.resourceType === resourceType).map((e) => e.resource);
}

function findById(entries: FhirEntry[], resourceType: string, id: string): Record<string, unknown> | null {
  const candidates = byType(entries, resourceType);
  if (id === "") return candidates[0] ?? null;
  return candidates.find((r) => r.id === id) ?? candidates[0] ?? null;
}

/** FHIR CodeableConcept -> display text: {text} first, else coding[0].display. */
function codeableConceptText(value: unknown): string {
  const obj = asObject(value);
  if (typeof obj.text === "string" && obj.text !== "") return obj.text;
  const coding = obj.coding;
  if (Array.isArray(coding) && coding.length > 0) {
    const first = asObject(coding[0]);
    if (typeof first.display === "string") return first.display;
  }
  return "";
}

/** FHIR Coding (not CodeableConcept -- no `coding` array, `display` sits directly on it) -> display text, e.g. Encounter.class. */
function codingText(value: unknown): string {
  const obj = asObject(value);
  return typeof obj.display === "string" ? obj.display : "";
}

/** FHIR Quantity -> "162 mg/dL". */
function quantityText(value: unknown): string {
  const obj = asObject(value);
  if (typeof obj.value !== "number") return "";
  const unit = typeof obj.unit === "string" ? obj.unit : "";
  return unit === "" ? String(obj.value) : `${obj.value} ${unit}`;
}

/** FHIR HumanName[] (Practitioner.name / Patient.name) -> the first entry's own {text}. */
function humanNameText(value: unknown): string {
  const obj = asObject(firstOf(value));
  return typeof obj.text === "string" ? obj.text : "";
}

/** "Practitioner/DOC0010" -> "DOC0010". */
function referenceId(value: unknown): string {
  const obj = asObject(value);
  const ref = obj.reference;
  if (typeof ref !== "string") return "";
  const parts = ref.split("/");
  return parts[parts.length - 1] ?? "";
}

function firstOf(value: unknown): unknown {
  return Array.isArray(value) ? value[0] : value;
}

interface FhirSection {
  icon: LucideIcon;
  title: string;
  lines: string[];
}

/** One structured section per resource type actually present -- see this file's own banner for why these exact field paths (grounded in repo/'s own real captured bundles, not generic FHIR). */
function buildFhirSections(entries: FhirEntry[]): FhirSection[] {
  const sections: FhirSection[] = [];

  const conditions = byType(entries, "Condition");
  if (conditions.length > 0) {
    sections.push({
      icon: Stethoscope,
      title: "Diagnosis",
      lines: conditions.map((c) => {
        const text = codeableConceptText(c.code) || "Unspecified condition";
        const date = typeof c.recordedDate === "string" ? c.recordedDate : typeof c.onsetDateTime === "string" ? c.onsetDateTime : "";
        return date === "" ? text : `${text} (recorded ${formatDate(date)})`;
      }),
    });
  }

  const medications = byType(entries, "MedicationRequest");
  if (medications.length > 0) {
    sections.push({
      icon: Pill,
      title: "Medications",
      lines: medications.map((m) => {
        const text = codeableConceptText(m.medicationCodeableConcept) || "Unspecified medication";
        const instruction = asObject(firstOf(m.dosageInstruction));
        const dosageText = typeof instruction.text === "string" ? instruction.text : "";
        return dosageText === "" ? text : `${text} — ${dosageText}`;
      }),
    });
  }

  const observations = byType(entries, "Observation");
  if (observations.length > 0) {
    const lines: string[] = [];
    for (const o of observations) {
      const components = o.component;
      if (Array.isArray(components) && components.length > 0) {
        for (const component of components) {
          const comp = asObject(component);
          const label = codeableConceptText(comp.code);
          const value = quantityText(comp.valueQuantity);
          if (label !== "" || value !== "") lines.push(`${label || "Reading"}: ${value || "—"}`);
        }
      } else {
        const label = codeableConceptText(o.code);
        const value = quantityText(o.valueQuantity);
        if (label !== "" || value !== "") lines.push(`${label || "Reading"}: ${value || "—"}`);
      }
    }
    if (lines.length > 0) sections.push({ icon: FileText, title: "Vitals", lines });
  }

  const diagnosticReports = byType(entries, "DiagnosticReport");
  if (diagnosticReports.length > 0) {
    sections.push({
      icon: FlaskConical,
      title: "Investigations",
      lines: diagnosticReports.map((d) => {
        const label = codeableConceptText(d.code);
        const conclusion = typeof d.conclusion === "string" ? d.conclusion : "";
        return conclusion === "" ? label || "Investigation (no conclusion recorded)" : conclusion;
      }),
    });
  }

  const immunizations = byType(entries, "Immunization");
  if (immunizations.length > 0) {
    sections.push({
      icon: Syringe,
      title: "Immunizations",
      lines: immunizations.map((i) => {
        const text = codeableConceptText(i.vaccineCode) || "Unspecified vaccine";
        const date = typeof i.occurrenceDateTime === "string" ? i.occurrenceDateTime : "";
        return date === "" ? text : `${text} (${formatDate(date)})`;
      }),
    });
  }

  const procedures = byType(entries, "Procedure");
  if (procedures.length > 0) {
    sections.push({
      icon: ClipboardList,
      title: "Procedures",
      lines: procedures.map((p) => {
        const text = codeableConceptText(p.code) || "Unspecified procedure";
        const date = typeof p.performedDateTime === "string" ? p.performedDateTime : "";
        return date === "" ? text : `${text} (${formatDate(date)})`;
      }),
    });
  }

  return sections;
}

interface FhirAttachment {
  id: string;
  contentType: string;
  dataUri: string;
  label: string;
}

/**
 * Scanned documents/images -- a real gap, not covered by buildFhirSections()
 * above at all. GROUNDED IN A REAL CAPTURED EXAMPLE (2026-09-03): a
 * successfully pulled and decrypted bundle carried a `Binary` resource
 * (contentType "image/jpeg", base64 `data`, ~130KB -- a scanned
 * prescription) referenced from the Composition's own "Prescription
 * record" section (`section[].entry[].reference === "Binary/<id>"`) --
 * every OTHER section type (Diagnosis, Medications, Vitals,
 * Investigations) was already rendered; this one silently had no code
 * path at all, so a record that pulled and decrypted successfully still
 * showed nothing for its own attached document.
 *
 * Section title is used as the attachment's label when a Binary is
 * referenced from one (matches how the record itself titled it, e.g.
 * "Prescription record") -- falls back to a generic label for a Binary
 * present in the bundle but not linked from any section, so it's still
 * shown rather than silently dropped if a different HIP's own data
 * shapes this differently.
 */
function extractAttachments(entries: FhirEntry[]): FhirAttachment[] {
  const binaries = byType(entries, "Binary");
  if (binaries.length === 0) return [];

  const composition = entries.find((e) => e.resourceType === "Composition")?.resource ?? null;
  const sections = Array.isArray(composition?.section) ? (composition?.section as unknown[]) : [];
  const labelByBinaryId = new Map<string, string>();
  for (const rawSection of sections) {
    const section = asObject(rawSection);
    const title = typeof section.title === "string" ? section.title : "";
    const sectionEntries = Array.isArray(section.entry) ? (section.entry as unknown[]) : [];
    for (const entry of sectionEntries) {
      const id = referenceId(entry);
      if (id !== "" && title !== "") labelByBinaryId.set(id, title);
    }
  }

  const attachments: FhirAttachment[] = [];
  for (const binary of binaries) {
    const id = typeof binary.id === "string" ? binary.id : "";
    const contentType = typeof binary.contentType === "string" ? binary.contentType : "";
    const data = typeof binary.data === "string" ? binary.data : "";
    if (contentType === "" || data === "") continue;
    attachments.push({
      id,
      contentType,
      dataUri: `data:${contentType};base64,${data}`,
      label: labelByBinaryId.get(id) || "Attached Document",
    });
  }
  return attachments;
}

function FhirRecordCard({ bundle, hipLabel }: { bundle: unknown; hipLabel: string }): JSX.Element {
  const entries = extractBundleEntries(bundle);
  const composition = entries.find((e) => e.resourceType === "Composition")?.resource ?? null;
  const encounter = entries.find((e) => e.resourceType === "Encounter")?.resource ?? null;
  const patient = entries.find((e) => e.resourceType === "Patient")?.resource ?? null;
  const practitioner = findById(entries, "Practitioner", referenceId(firstOf(composition?.author)));
  const organization = findById(entries, "Organization", referenceId(composition?.custodian ?? encounter?.serviceProvider));

  const facilityName = (typeof organization?.name === "string" ? organization.name : "") || hipLabel;
  const encounterClass = codingText(encounter?.class);
  const reportType = codeableConceptText(composition?.type) || "Clinical record";
  const practitionerName = humanNameText(practitioner?.name);
  const visitDate = typeof asObject(encounter?.period).start === "string" ? (asObject(encounter?.period).start as string) : "";
  const patientName = humanNameText(patient?.name);
  const patientGender = typeof patient?.gender === "string" ? patient.gender : "";
  const patientBirthDate = typeof patient?.birthDate === "string" ? patient.birthDate : "";

  const sections = buildFhirSections(entries);
  const attachments = extractAttachments(entries);

  return (
    <Card padding="md" className="ui-card--flush">
      <CardBody>
        <div className="ui-card__header">
          <CardTitle icon={Building2}>{facilityName}</CardTitle>
        </div>
        <p className="muted">{[encounterClass, reportType].filter((v) => v !== "").join(" · ")}</p>

        <div className="field">
          <span className="field__label">Practitioner</span>
          <span className="field__value">{practitionerName || "—"}</span>
        </div>
        <div className="field">
          <span className="field__label">Clinic</span>
          <span className="field__value">{facilityName}</span>
        </div>
        <div className="field">
          <span className="field__label"><Calendar size={12} aria-hidden="true" /> Visit date</span>
          <span className="field__value">{formatDate(visitDate) || "—"}</span>
        </div>
        <div className="field">
          <span className="field__label"><UserRound size={12} aria-hidden="true" /> Patient</span>
          <span className="field__value">
            {patientName || "—"}
            {patientGender !== "" ? ` · ${patientGender}` : ""}
            {patientBirthDate !== "" ? ` · born ${formatDate(patientBirthDate)}` : ""}
          </span>
        </div>

        {sections.length === 0 ? (
          <p className="muted">No structured clinical sections were found in this record — see the raw bundle below.</p>
        ) : (
          sections.map((section) => (
            <div key={section.title} className="field field--block">
              <span className="field__label">
                <section.icon size={12} aria-hidden="true" /> {section.title}
              </span>
              <ul>
                {section.lines.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            </div>
          ))
        )}

        {attachments.map((attachment) => (
          <div key={attachment.id || attachment.dataUri} className="field field--block">
            <span className="field__label">
              <FileText size={12} aria-hidden="true" /> {attachment.label}
            </span>
            {attachment.contentType.startsWith("image/") ? (
              <a href={attachment.dataUri} target="_blank" rel="noreferrer">
                <img src={attachment.dataUri} alt={attachment.label} style={{ maxWidth: "100%", borderRadius: 8 }} />
              </a>
            ) : (
              <a href={attachment.dataUri} download={`${attachment.label}${attachment.id ? `-${attachment.id}` : ""}`}>
                <Download size={12} aria-hidden="true" /> Download ({attachment.contentType})
              </a>
            )}
          </div>
        ))}
      </CardBody>
      <CardFooter>
        <RawBody label="bundle (raw FHIR)" result={wrapAsResult(bundle, "(decrypted FHIR bundle, from the data-flow status response)")} />
      </CardFooter>
    </Card>
  );
}

// --- P9: self-view consent auto-provisioning -----------------------------
// See this file's own banner for the full story: extractCoveringConsents()
// above now only recognizes a PATRQT-purposed, GRANTED artefact as
// "covering" a HIP -- these are what raise one automatically, so the
// patient doesn't have to manually approve their own self-view (per the
// working assumption below), while always leaving a working manual
// fallback if that assumption turns out wrong for this project's own
// registration.

/**
 * P11 (2026-09-02) -- our own requester identity for self-view requests,
 * MUST match data_flow.py's own request_self_view_consent() literally
 * (requester_name="Aegle PHR — My Records") -- this is what tells "a
 * PATRQT request/artefact WE raised" apart from "a PATRQT request/
 * artefact some OTHER app raised" (ABDM's own external sandbox app
 * raises its own PATRQT self-grant on every link too, using its own,
 * different requester name). See the P11 section of this file's own
 * banner for the confirmed live bug this closes -- purpose.code alone,
 * with no check on WHO raised it, let a foreign app's own pending/
 * granted PATRQT request permanently block us from ever raising (or
 * using) our own.
 */
/**
 * Shown when a facility's records are not (yet) pullable. P19 replaced
 * SelfViewWaitingCallout, which narrated a raise-and-poll cycle this app
 * no longer performs: the locker's own auto-approval grants its consents,
 * so there is nothing for the patient to wait on or approve by hand.
 * What IS worth telling them apart is whether the locker is switched on
 * at all -- that is the one thing they can act on.
 */
function NoCoverageCallout({ lockerOn }: { lockerOn: boolean }): JSX.Element {
  if (!lockerOn) {
    return (
      <Callout tone="info">
        Automatic record collection is off, so nothing has been fetched from this facility yet. You
        can switch it on under Subscriptions.
      </Callout>
    );
  }
  return (
    <Callout tone="info">
      Nothing has arrived from this facility yet. New records appear on their own once the facility
      shares them — there is nothing you need to do.
    </Callout>
  );
}

export function HomeScreen(): JSX.Element {
  const navigate = useNavigate();
  const [sessionToken] = useState(() => getSessionToken());
  const [sessionAddress] = useState(() => getSessionAddress());
  /** P14 -- purely a client-side substring filter over facilities already
   * fetched below (groupByHip(linkedRecords)), matching the reference
   * app's own search box (design_reference/01_home.png). No new API call,
   * no change to what's fetched or when -- filters the same in-memory
   * list this screen already renders. */
  const [facilitySearch, setFacilitySearch] = useState("");
  const [profileResult, setProfileResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [linksResult, setLinksResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [consentArtefactsResult, setConsentArtefactsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const [selectedHip, setSelectedHip] = useState<HipGroup | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<LinkedRecord | null>(null);
  const [pullStateByHip, setPullStateByHip] = useState<Record<string, PullState>>({});
  const autoFetchTriggeredRef = useRef<Set<string>>(new Set());

  /**
   * P19 -- our own locker's status, read once per login. Two jobs:
   *   1. lockerId is the discriminator extractCoveringConsents() uses to
   *      tell OUR consents from any other app's.
   *   2. subscriptionUsable / needsOptIn drive what this screen tells a
   *      patient when a facility has nothing to show yet.
   *
   * Replaces the P9-P13 self-view state this component used to carry --
   * selfViewState, selfViewRunningRef, autoApproveEnsuredRef and the
   * knownBadConsentIds set (with its localStorage persistence). All of
   * that existed to raise a self-view consent, poll for it to be granted,
   * and remember which candidates were permanently unusable. The locker's
   * own auto-approval policy does that job now, server-side, so none of
   * it has anything left to do.
   */
  const [lockerStatus, setLockerStatus] = useState<LockerStatus | null>(null);
  const lockerId = lockerStatus?.lockerId ?? "";
  const lockerOn = lockerStatus?.subscriptionUsable === true;

  /** P20 -- NOT_STARTED / RUNNING / DONE / FAILED for the one-off backfill. */
  const [lockerSyncState, setLockerSyncState] = useState<string>("");
  const [lockerRecordCount, setLockerRecordCount] = useState<number>(0);

  /**
   * P20 -- reads the locker's own storage and seeds the per-HIP display
   * state from it. Safe to call repeatedly: it replaces the seeded state
   * wholesale rather than accumulating, and the backend sweeps lapsed
   * consents before returning anything, so a record we are no longer
   * entitled to hold disappears here on the very next read.
   */
  async function loadLockerRecords(): Promise<void> {
    if (sessionAddress === "") return;
    const result = await getLockerRecords({
      patientAbhaAddress: sessionAddress,
      xToken: sessionToken,
    });
    const body = result.data?.body as
      | { records?: LockerRecord[]; count?: number; initialSyncState?: string }
      | undefined;
    if (!body) return;

    setLockerSyncState(body.initialSyncState ?? "");
    setLockerRecordCount(body.count ?? 0);

    const seeded = pullStateFromLockerRecords(body.records ?? []);
    // MERGE, not replace: a HIP the patient has manually pulled during
    // this session keeps that pull state, because it may hold something
    // the locker has not collected yet.
    setPullStateByHip((current) => ({ ...current, ...seeded }));
  }

  useEffect(() => {
    if (sessionToken === "") return;
    void getProfile({ xToken: sessionToken }).then(setProfileResult);
    void getAllLinkedRecords({ xToken: sessionToken }).then(setLinksResult);
    // limit/status EXPLICIT (2026-09-05, real bug found live): omitting
    // them defaults server-side (GetAllConsentArtefactsBody, aegle_phr/
    // phr/schemas.py) to limit=10, status="ALL" -- fine for an account
    // with a handful of consents, but confirmed live to silently truncate
    // a real patient's list: Pooja Rameshkumar has accumulated 15-20+
    // consent artefacts across facilities, so only an arbitrary first-10
    // page (of every status, not just GRANTED) ever reached
    // extractCoveringConsents() below -- her MS Hospital umbrella consent
    // (the one covering all 4 of that HIP's linked care contexts) fell
    // outside that page and never became a pull candidate at all, no
    // matter how correct the multi-consent merge logic downstream is.
    // limit=100/status="GRANTED" matches data_flow.py's own
    // discover_self_view_consents() call to the same #9 endpoint, which
    // is exactly why the backend had these consents locally registered
    // even though this frontend fetch was silently missing them.
    void getAllConsentArtefacts({ xToken: sessionToken, limit: 100, status: "GRANTED" }).then(setConsentArtefactsResult);
    // P19 -- read our own locker's status once per login. This replaces
    // three fire-and-forget self-view calls that used to sit here
    // (discoverSelfViewConsents, ensureSelfSubscription and
    // ensureSelfViewAutoApprove): between them they discovered another
    // app's granted consents and registered them locally, and stood up a
    // self-subscription and auto-approval policy under a borrowed HIU id.
    // The locker does all of that properly now, so the only thing this
    // screen still needs from the backend is which locker is ours and
    // whether it is switched on.
    if (sessionAddress !== "") {
      void getLockerStatus({ xToken: sessionToken, patientAbhaAddress: sessionAddress })
        .then((result) => { if (result.data) setLockerStatus(result.data); });

      // P20 -- READ WHAT THE LOCKER ALREADY HOLDS. No ABDM round trip:
      // the records were collected when they became available and are
      // ours to keep for the life of the consent behind them. xToken is
      // passed for one reason only -- if the one-off backfill has never
      // run, it is what lets the backend start it (in the background;
      // this call does not wait for it, and the poll below picks it up).
      void loadLockerRecords();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionToken]);

  /*
   * P20 -- poll ONLY while the one-off backfill is running.
   *
   * The backfill is a real ABDM round trip per hospital (5-10s observed
   * live), so a first-ever login legitimately shows an empty locker for a
   * few seconds while history arrives. Polling stops the moment it
   * reports DONE or FAILED -- this is not a background refresh loop, and
   * a locker that is already synced never polls at all.
   */
  useEffect(() => {
    if (lockerSyncState !== "RUNNING") return;
    const timer = window.setInterval(() => { void loadLockerRecords(); }, BACKFILL_POLL_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockerSyncState, sessionToken, sessionAddress]);

  /*
   * P20 -- keep the screen current while it is open.
   *
   * WHY THIS IS NEEDED. The locker collects a newly linked visit on its
   * own, within seconds of the 8.3.11 alert -- but the screen read its
   * records once, at login. Without this, a record that arrived while the
   * patient was looking at the app stayed invisible until they reloaded,
   * which makes "new records appear automatically" true of the locker and
   * false of the app.
   *
   * CHEAP BY CONSTRUCTION. This hits /phr/locker/records, which is a local
   * database read -- no ABDM call, no consent, no data request. So a slow
   * poll costs essentially nothing, unlike the pre-P20 model where
   * refreshing meant a health-information request per hospital.
   *
   * Also refreshes on window focus, which is what actually catches the
   * common case: the patient switches away, a record arrives, they switch
   * back. Skipped entirely while the backfill is RUNNING, so the two
   * effects never poll at once.
   */
  useEffect(() => {
    if (sessionAddress === "" || lockerSyncState === "RUNNING") return;

    const refresh = (): void => { void loadLockerRecords(); };
    const timer = window.setInterval(refresh, RECORDS_POLL_MS);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockerSyncState, sessionToken, sessionAddress]);

  const linkedRecords = extractLinkedRecords(linksResult?.data?.body ?? null);
  const coveringConsents = extractCoveringConsents(consentArtefactsResult?.data?.body ?? null, lockerId);

  /*
   * P19 removed the self-view auto-provisioning effect that lived here.
   * It watched for any linked HIP with no covering consent, raised a
   * PATRQT self-view request for it, then polled ABDM for that request to
   * flip to GRANTED, narrating each phase through SelfViewWaitingCallout.
   *
   * None of that is needed now. The locker holds a subscription for the
   * patient, so ABDM sends an alert whenever a new care context is linked;
   * the backend raises a consent as the locker and the locker's own
   * auto-approval policy grants it without the patient doing anything.
   * There is no request for this screen to raise and nothing to poll for.
   * What the patient sees instead, when a facility has nothing yet, is
   * NoCoverageCallout.
   */


  /**
   * Polls one already-initiated request's status until "complete" or the
   * attempt budget runs out -- factored out from pullRecords() so
   * "Check again" (after a timeout) can RESUME polling the SAME
   * requestId instead of calling pullRecords() again, which would fire a
   * brand-new initiate_health_information_request() and risk exactly the
   * duplicate-transaction problem that module's own docstring flags (the
   * HIP could end up pushing -- and encrypting -- the same records
   * twice, under two different transactionIds). A timeout here does NOT
   * mean the request failed -- the on-request ack can (and, confirmed
   * live 2026-09-01 against a real "MS Hospital" pull, sometimes does)
   * land fine while the HIP's own push simply takes longer than this
   * screen's own budget.
   */
  /** Patches ONE consent's own slot within pullStateByHip[hipKey].consents, leaving every other consent's own entry (for this HIP or any other) untouched -- the per-consent equivalent of the old flat setPullStateByHip() updates, now that a HIP can have several consents pulling independently at once (see PullState's own banner). No-ops if the slot doesn't exist yet (shouldn't happen -- every caller below creates the slot before patching it). */
  const updateConsentPullState = (hipKey: string, consentId: string, patch: Partial<ConsentPullState>): void => {
    setPullStateByHip((prev) => {
      const current = prev[hipKey] ?? EMPTY_PULL_STATE;
      const consents = current.consents.map((c) => (c.consentId === consentId ? { ...c, ...patch } : c));
      return { ...prev, [hipKey]: { ...current, consents } };
    });
  };

  /**
   * Polls one already-initiated request's status until "complete" or the
   * attempt budget runs out -- factored out from pullOneConsent() so
   * "Check again" (after a timeout) can RESUME polling the SAME
   * requestId instead of calling pullOneConsent() again, which would fire
   * a brand-new initiate_health_information_request() and risk exactly
   * the duplicate-transaction problem that module's own docstring flags
   * (the HIP could end up pushing -- and encrypting -- the same records
   * twice, under two different transactionIds). A timeout here does NOT
   * mean the request failed -- the on-request ack can (and, confirmed
   * live 2026-09-01 against a real "MS Hospital" pull, sometimes does)
   * land fine while the HIP's own push simply takes longer than this
   * screen's own budget.
   */
  const pollStatus = async (hipKey: string, consentId: string, requestId: string): Promise<void> => {
    updateConsentPullState(hipKey, consentId, { busy: true, timedOut: false });
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      await sleep(POLL_INTERVAL_MS);
      const statusResult = await getHealthInformationStatus(requestId);
      const careContexts = extractPulledCareContexts(statusResult.data?.body ?? null);
      updateConsentPullState(hipKey, consentId, { statusResult, careContexts });
      if (careContexts !== null) {
        updateConsentPullState(hipKey, consentId, { busy: false });
        return;
      }
    }
    // A genuine timeout (POLL_MAX_ATTEMPTS x POLL_INTERVAL_MS, 90s --
    // generous) means the HIP never pushed anything for this consent's own
    // care context(s), confirmed live for consents pointing at old/
    // regenerated test data that no longer exists on the HIP side.
    //
    // P19 no longer records the consent as permanently bad here. That
    // existed so the self-view effect would stop trusting an unusable
    // candidate and raise its own request instead -- and that effect is
    // gone. A locker consent that times out is worth retrying (the HIP may
    // simply have had nothing to push yet), so the timeout is surfaced on
    // this pull and nothing is blacklisted across sessions.
    updateConsentPullState(hipKey, consentId, { busy: false, timedOut: true });
  };

  /**
   * Runs ONE covering consent's own full request -> (recover) -> poll
   * cycle, updating only its own slot in pullStateByHip[hipKey].consents.
   * Factored out of pullRecords() (2026-09-05) so a HIP with several
   * usable covering consents can pull ALL of them concurrently -- see
   * pullRecords()'s own comment for why this, not one request covering
   * everything, is the actual fix for "only 1 of N linked records
   * visible": ABDM's data-flow request only ever returns what the ONE
   * consent it names covers, so getting everything a patient has been
   * granted means calling this once per usable consent and merging their
   * results (mergedCareContexts()), not finding a way to ask for more in
   * a single call.
   */
  const pullOneConsent = async (hipKey: string, covering: CoveringConsent): Promise<void> => {
    updateConsentPullState(hipKey, covering.consentId, { busy: true, timedOut: false });

    let requestResult = await requestHealthInformation({
      consentId: covering.consentId,
      hipId: covering.hipId,
      hiuId: covering.hiuId,
      dateRangeFrom: covering.periodFrom,
      dateRangeTo: covering.periodTo,
    });
    updateConsentPullState(hipKey, covering.consentId, { requestResult });

    /**
     * P12 -- CONFIRMED LIVE (2026-09-02, real evidence, not inferred):
     * ABDM's own HIU-notify callback -- what NORMALLY triggers repo/'s
     * own fetch_consent() automatically once a request is GRANTED --
     * never fires for a self-requested (PATRQT) consent, even though
     * the SAME account's own on-init ack and the SAME day's third-
     * party (CAREMGT) notify callbacks both worked completely
     * normally. So a GENUINELY OURS, GENUINELY GRANTED PATRQT consent
     * (P11 already guarantees requester.name matched before this
     * candidate was ever offered) can STILL fail this first attempt --
     * not because it's foreign or broken, but because nothing ever
     * told repo/ to go fetch it. Recovery: explicitly call
     * trigger_consent_fetch() ourselves (data_flow.py), then retry the
     * SAME pull a few bounded times, giving the (separately, already
     * proven working) on-fetch callback time to land. Only marked
     * known-bad (P10's own mechanism) if it STILL fails after this --
     * at that point it really is unrecoverable from here.
     */
    if (requestResult.data?.reasonCode === "consent_not_in_local_cache") {
      const triggerResult = await triggerConsentFetch({ consentId: covering.consentId, hiuId: covering.hiuId });
      if (triggerResult.data?.ok === true) {
        for (let attempt = 1; attempt <= FETCH_TRIGGER_MAX_ATTEMPTS; attempt += 1) {
          updateConsentPullState(hipKey, covering.consentId, { fetchTriggerAttempt: attempt });
          await sleep(FETCH_TRIGGER_RETRY_INTERVAL_MS);
          requestResult = await requestHealthInformation({
            consentId: covering.consentId,
            hipId: covering.hipId,
            hiuId: covering.hiuId,
            dateRangeFrom: covering.periodFrom,
            dateRangeTo: covering.periodTo,
          });
          updateConsentPullState(hipKey, covering.consentId, { requestResult, fetchTriggerAttempt: 0 });
          if (requestResult.data?.reasonCode !== "consent_not_in_local_cache") break;
        }
      }
    }

    const requestId = stringField(requestResult.data?.body, "requestId");
    if (requestResult.data?.ok !== true || requestId === "") {
      // P10 -- this exact, machine-checkable signal (not a string-match
      // on the human-readable error) means covering.consentId is
      // genuinely unrecoverable from here -- either a foreign artefact
      // (shouldn't reach this point at all post-P11, but kept as a
      // backstop), or ours but the P12 recovery above was also
      // exhausted without success. Marking it known-bad here is what
      // P19: "consent_not_in_local_cache" used to mean a foreign app's
      // consent had been mistaken for ours, and the id was blacklisted so
      // the self-view effect would raise our own. extractCoveringConsents()
      // now only ever returns consents whose hiu.id IS our locker, so that
      // mix-up cannot happen; if this still fires it means repo/ has not
      // finished registering a genuinely-ours consent yet, which a later
      // pull resolves. Surfaced, not blacklisted.
      updateConsentPullState(hipKey, covering.consentId, { busy: false });
      return;
    }

    updateConsentPullState(hipKey, covering.consentId, { requestId });
    await pollStatus(hipKey, covering.consentId, requestId);
  };

  /**
   * Pulls EVERY usable covering consent for this HIP, concurrently, and
   * lets mergedCareContexts() combine whatever each one returns.
   * REWRITTEN (2026-09-05) from a single request/poll cycle per HIP --
   * see extractCoveringConsents()'s own banner for the real bug this
   * fixes: a HIP can have more than one GRANTED self-view consent at
   * once, each covering a DIFFERENT subset of that HIP's linked care
   * contexts (confirmed live -- one covering all 4 of a patient's linked
   * records, three more each covering just 1), and ABDM's own data-flow
   * request only ever returns what the ONE consent it names covers.
   * Using just one of them (the old behavior) silently capped how many
   * records ever became visible at whatever that one consent happened to
   * cover. This is a deliberate, explicit "Pull/Refresh" action, so it
   * always restarts every covering consent's own request from scratch
   * (unlike the auto-fetch effect below, which must never redo a consent
   * it already successfully pulled).
   */
  const pullRecords = (hipKey: string): void => {
    const coveringList = coveringConsents.get(hipKey) ?? [];
    if (coveringList.length === 0) {
      setPullStateByHip((prev) => ({ ...prev, [hipKey]: { noConsent: true, consents: [] } }));
      return;
    }
    setPullStateByHip((prev) => ({
      ...prev,
      [hipKey]: {
        noConsent: false,
        consents: coveringList.map((c) => ({ ...emptyConsentPullState(c.consentId), busy: true })),
      },
    }));
    for (const covering of coveringList) {
      void pullOneConsent(hipKey, covering);
    }
  };

  /** Resumes polling every TIMED-OUT consent's own already-in-flight request for this HIP -- see pollStatus()'s own docstring for why this is NOT the same as calling pullRecords() again. A consent that already succeeded, or is still busy, is left alone -- only the ones that genuinely timed out (and therefore have a requestId sitting idle) get re-polled. */
  const checkAgain = (hipKey: string): void => {
    const pullState = pullStateByHip[hipKey];
    if (pullState === undefined) return;
    for (const c of pullState.consents) {
      if (c.timedOut && c.requestId !== "") {
        void pollStatus(hipKey, c.consentId, c.requestId);
      }
    }
  };

  /**
   * P9 item 3 -- auto-fetch. Once a HIP has a covering (PATRQT-GRANTED)
   * consent, its records should be pulled without the patient clicking
   * anything. Fires pullOneConsent() once per CANDIDATE the first time it
   * becomes covering (autoFetchTriggeredRef guards this synchronously,
   * since pullStateByHip's own "busy" entry doesn't land until
   * pullOneConsent()'s own async body actually runs -- a ref avoids a
   * race where this effect could fire the same candidate twice before
   * that state commits). Manual re-pull stays available regardless (the
   * existing "Pull Records"/"Refresh" buttons below).
   *
   * KEYED BY consentId, NOT hipKey (P10, 2026-09-02) -- deliberately: a
   * HIP's own set of covering consents can CHANGE over the page's own
   * lifetime (a foreign, known-bad PATRQT artefact getting replaced by
   * our own newly-granted one, or -- since P14's rewrite -- a genuinely
   * NEW additional covering consent simply appearing alongside ones
   * already being pulled, see extractCoveringConsents()'s own banner).
   * Keying on hipKey alone would mean this effect only ever acts once per
   * HIP, total, ignoring every consent discovered after the first. Keying
   * on consentId instead means: never auto-retry the EXACT SAME candidate
   * twice (satisfies "don't keep hammering a known-bad consent id"), but
   * a NEW consentId for a HIP that's already partially covered still gets
   * its own automatic attempt, ALONGSIDE (not instead of) whatever this
   * HIP's other already-triggered consents are doing.
   */
  useEffect(() => {
    for (const [hipKey, coveringList] of coveringConsents) {
      for (const covering of coveringList) {
        if (autoFetchTriggeredRef.current.has(covering.consentId)) continue;
        autoFetchTriggeredRef.current.add(covering.consentId);
        setPullStateByHip((prev) => {
          const current = prev[hipKey] ?? EMPTY_PULL_STATE;
          if (current.consents.some((c) => c.consentId === covering.consentId)) return prev;
          return {
            ...prev,
            [hipKey]: {
              noConsent: false,
              consents: [...current.consents, { ...emptyConsentPullState(covering.consentId), busy: true }],
            },
          };
        });
        void pullOneConsent(hipKey, covering);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consentArtefactsResult]);

  if (sessionToken === "") {
    return (
      <section className="panel">
        <PageHeader icon={Home} title="Home" />
        <p className="muted">Log in first (Password or Mobile/OTP login).</p>
      </section>
    );
  }

  const body = profileResult?.data?.body ?? null;
  const abhaNumber = stringField(body, "abhaNumber");
  const abhaAddress = stringField(body, "abhaAddress") || sessionAddress;
  const photo = stringField(body, "profilePhoto") || stringField(body, "photo");

  // --- Level 3: one record's own pulled clinical content -------------------
  if (selectedHip !== null && selectedRecord !== null) {
    const pullState = pullStateByHip[selectedHip.key] ?? EMPTY_PULL_STATE;
    const careContexts = mergedCareContexts(pullState);
    const busy = isPullBusy(pullState);
    const timedOut = isPullTimedOut(pullState);
    const matched = selectedRecord.careContexts
      .map((cc) => ({ cc, result: careContexts?.[cc.referenceNumber] }))
      .filter((entry): entry is { cc: LinkedCareContext; result: PulledCareContext } => entry.result !== undefined);

    return (
      <section className="panel">
        <PageHeader
          icon={Home}
          title="Home"
          actions={
            careContexts !== null ? (
              <Button size="sm" icon={busy ? Loader2 : RefreshCw} disabled={busy} onClick={() => pullRecords(selectedHip.key)}>
                {busy ? "Refreshing…" : "Refresh"}
              </Button>
            ) : undefined
          }
        />
        <Button size="sm" icon={ArrowLeft} onClick={() => setSelectedRecord(null)}>Back</Button>

        {!coveringConsents.has(selectedHip.key) && careContexts === null && (
          <NoCoverageCallout lockerOn={lockerOn} />
        )}
        {busy && <p className="muted">{pullPhaseMessage(pullState)}</p>}
        {timedOut && (
          <Callout tone="warning">
            <p style={{ margin: 0 }}>
              Timed out after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000)} seconds — this
              does <strong>not</strong> mean it failed. Check again rather than pulling again, to avoid
              starting a second, separate request for the same records.
            </p>
            <Button size="sm" icon={RefreshCw} onClick={() => checkAgain(selectedHip.key)}>Check again</Button>
          </Callout>
        )}
        {careContexts === null ? (
          <EmptyState
            icon={Inbox}
            message="Nothing pulled yet for this record."
            action={
              coveringConsents.has(selectedHip.key) ? (
                <Button variant="primary" icon={Download} disabled={busy} onClick={() => pullRecords(selectedHip.key)}>
                  {busy ? "Pulling…" : "Pull Records"}
                </Button>
              ) : undefined
            }
          />
        ) : matched.length === 0 ? (
          <EmptyState icon={Inbox} message="This record's own care context wasn't part of the last pull -- try pulling again." />
        ) : (
          matched.map(({ cc, result }) => {
            const ok = result.hiStatus.toUpperCase() === "OK";
            return (
              <div key={cc.referenceNumber} className="field field--block">
                <div className="ui-card__header">
                  <span className="ui-card__label">{cc.referenceNumber}</span>
                  <Badge tone={ok ? "success" : "danger"}>{result.hiStatus || "Unknown"}</Badge>
                </div>
                {ok ? (
                  <FhirRecordCard bundle={result.bundle} hipLabel={selectedHip.label} />
                ) : (
                  <p className="result result--error">{result.description || "No further detail given."}</p>
                )}
              </div>
            );
          })
        )}
      </section>
    );
  }

  // --- Level 2: one HIP's own linked records --------------------------------
  if (selectedHip !== null) {
    const pullState = pullStateByHip[selectedHip.key] ?? EMPTY_PULL_STATE;
    const careContexts = mergedCareContexts(pullState);
    const busy = isPullBusy(pullState);
    const timedOut = isPullTimedOut(pullState);
    const timedOutConsent = pullState.consents.find((c) => c.timedOut);
    return (
      <section className="panel">
        <PageHeader icon={Home} title="Home" />
        <Button size="sm" icon={ArrowLeft} onClick={() => setSelectedHip(null)}>Back to facilities</Button>
        <PageHeader
          icon={Building2}
          title={selectedHip.label}
          actions={
            coveringConsents.has(selectedHip.key) ? (
              <Button variant="primary" icon={busy ? Loader2 : Download} disabled={busy} onClick={() => pullRecords(selectedHip.key)}>
                {busy ? "Pulling…" : careContexts !== null ? "Refresh" : "Pull Records"}
              </Button>
            ) : undefined
          }
        />

        {!coveringConsents.has(selectedHip.key) && <NoCoverageCallout lockerOn={lockerOn} />}
        {pullState.noConsent && (
          <Callout tone="warning">
            No GRANTED consent found for this facility -- Data Flow (spec §7) needs one to pull real
            record content. Approve a consent request covering this facility in Consent Manager first.
          </Callout>
        )}
        {busy && (
          <p className="muted">{pullPhaseMessage(pullState)}</p>
        )}
        {timedOut && (
          <Callout tone="warning">
            <p style={{ margin: 0 }}>
              Timed out after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000)} seconds waiting
              for this facility to push the records. This does <strong>not</strong> mean it failed —
              {stringField(timedOutConsent?.statusResult?.data?.body, "phase") === "transaction_assigned"
                ? " the facility already acknowledged the request; it may just be slow to push the actual data."
                : " it may still be in flight on ABDM's own side."} Check again rather than pulling
              again, to avoid starting a second, separate request for the same records.
            </p>
            <Button size="sm" icon={RefreshCw} onClick={() => checkAgain(selectedHip.key)}>Check again</Button>
          </Callout>
        )}
        {pullState.consents.map((c) => (
          <div key={c.consentId}>
            <RawBody label={`data-flow/request (${c.consentId.slice(0, 8)})`} result={c.requestResult} />
            <RawBody label={`data-flow/status (${c.consentId.slice(0, 8)})`} result={c.statusResult} />
          </div>
        ))}

        <CardGrid minWidth={280}>
          {/* One card per ACTUAL care context (flattenToCareContextRows()'s own banner) -- NOT one
              per raw ABDM link object. record.display (the link-level field) used to be shown here,
              but ABDM sets it to the PATIENT's name -- identical across every linked record at a HIP
              -- so two genuinely different records with the same hiType were visually indistinguishable.
              FIXED 2026-09-05, real bug found live twice over: first, a just-linked record looked
              identical to an existing one (fixed by showing the care-context-level display instead of
              the patient name); second, ABDM had bundled 2 of 3 newly-linked care contexts into a
              SINGLE link object, so even with the display fix those two still shared one card instead
              of getting one each. Flattening to one row per care context (rather than looping over
              record.careContexts INSIDE one card) fixes both at once. */}
          {flattenToCareContextRows(selectedHip.records).map(({ parent, careContext }, index) => (
            <Card key={`${careContext.referenceNumber}-${index}`} padding="sm">
              <CardTitle icon={FileText}>{parent.hiType || "Record"}</CardTitle>
              <CardBody>
                <p className="ui-card__value">{careContext.display || careContext.referenceNumber}</p>
                <p className="ui-card__label">Linked</p>
                <p className="ui-card__value">{formatDate(parent.dateCreated) || "—"}</p>
              </CardBody>
              <CardFooter>
                <Button size="sm" icon={Eye} onClick={() => setSelectedRecord({ ...parent, careContexts: [careContext] })}>View Details</Button>
                {coveringConsents.has(selectedHip.key) && (
                  <Button
                    size="sm"
                    icon={busy ? Loader2 : Download}
                    disabled={busy}
                    onClick={() => pullRecords(selectedHip.key)}
                  >
                    {careContexts !== null ? "Refresh" : "Pull Records"}
                  </Button>
                )}
              </CardFooter>
            </Card>
          ))}
        </CardGrid>
      </section>
    );
  }

  // --- Level 1: profile + one card per HIP ----------------------------------
  const hipGroups = linkedRecords !== null ? groupByHip(linkedRecords) : [];
  const visibleHipGroups =
    facilitySearch.trim() === ""
      ? hipGroups
      : hipGroups.filter((group) => group.label.toLowerCase().includes(facilitySearch.trim().toLowerCase()));

  return (
    <section>
      {profileResult === null && <p className="muted">Loading your profile…</p>}

      {profileResult?.data?.ok === true && (
        <>
          <ProfileHeader
            photoBase64={photo}
            name={abhaAddress || "Your account"}
            kycStatus=""
            onSwitchAccount={() => navigate("/profile")}
          />
          <div className="ui-info-stack" style={{ marginTop: "var(--space-3)" }}>
            <InfoRow icon={IdCard} label="ABHA Number" value={abhaNumber || "—"} />
            <InfoRow icon={UserRound} label="ABHA Address" value={abhaAddress} />
          </div>
        </>
      )}

      {profileResult !== null && profileResult.data?.ok !== true && (
        <p className="result result--error">Couldn&apos;t load your profile — check the Console for details.</p>
      )}

      {/*
        P20 -- the first-login wait, made legible.

        The one-off backfill is a real ABDM round trip per hospital, so a
        brand-new locker genuinely shows nothing for a few seconds. Without
        this the screen is just empty, which reads as "this app has none of
        my records" rather than "they are on their way". Only ever shown
        while the backfill is actually RUNNING; a synced locker never
        renders it, because after that first pass records are already here.
      */}
      {lockerSyncState === "RUNNING" && (
        <Callout tone="info">
          Collecting your existing records from your hospitals — this happens once, and takes a few
          seconds. {lockerRecordCount > 0
            ? `${lockerRecordCount} so far.`
            : "New records will appear here as they arrive."}
        </Callout>
      )}
      {lockerSyncState === "FAILED" && (
        <Callout tone="warning">
          Some of your existing records couldn&apos;t be collected. Anything already here is shown
          below, and new records will still arrive on their own.
        </Callout>
      )}

      <Card padding="md" className="ui-card--flush" style={{ marginTop: "var(--space-4)" }}>
        <CardBody>
          {/* No "Consent Manager" shortcut here anymore -- it's the raised
              center tab in the bottom nav now, one tap away from every
              screen; repeating it here was exactly the kind of redundant
              chrome this pass is meant to remove. */}
          <CardTitle icon={Building2}>My Health Records</CardTitle>
          <p className="muted">
            Facilities already linked to this account via HIP-Initiated Linking. Tap one to see its
            records and pull the actual clinical content for a granted consent.
          </p>

          <div className="ui-search">
            <Search size={16} className="ui-search__icon" aria-hidden="true" />
            <input
              type="text"
              placeholder="Search your Hospital, Clinic or Lab"
              value={facilitySearch}
              onChange={(event) => setFacilitySearch(event.target.value)}
            />
          </div>

          {linksResult === null && <p className="muted">Loading…</p>}

          {linksResult !== null && linksResult.data?.ok !== true && (
            <p className="result result--error">Couldn&apos;t load linked records — check the Console for details.</p>
          )}

          {linkedRecords !== null && linkedRecords.length === 0 && (
            <EmptyState icon={Inbox} message="No linked records for this account." />
          )}

          {linkedRecords !== null && linkedRecords.length > 0 && visibleHipGroups.length === 0 && (
            <EmptyState icon={Search} message={`No facility matches "${facilitySearch}".`} />
          )}

          {visibleHipGroups.length > 0 && (
            <div className="ui-card--flush">
              {visibleHipGroups.map((group) => (
                <ListRow key={group.key} icon={Building2} onClick={() => setSelectedHip(group)}>
                  {group.label}
                  {" "}
                  <Badge tone={coveringConsents.has(group.key) ? "success" : "neutral"}>
                    {/* Counts actual care contexts (flattenToCareContextRows()), not raw ABDM link
                        objects -- group.records.length used to undercount whenever ABDM bundled
                        several care contexts into one link object (see that function's own banner),
                        so this badge and the actual number of cards shown one level in used to disagree. */}
                    {(() => {
                      const count = flattenToCareContextRows(group.records).length;
                      return `${count} record${count === 1 ? "" : "s"}`;
                    })()}
                  </Badge>
                </ListRow>
              ))}
            </div>
          )}

          {linksResult?.data?.ok === true && linkedRecords === null && (
            <p className="muted">
              The response didn&apos;t match the expected shape — turn on "Show raw responses" (menu,
              top left) to see exactly what came back.
            </p>
          )}
          <RawBody label="links/get-all" result={linksResult} />
        </CardBody>
      </Card>
    </section>
  );
}
