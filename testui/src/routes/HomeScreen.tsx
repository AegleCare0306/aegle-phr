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
 * DATA FLOW (spec §7) LIVES HERE NOW, NOT IN CONSENT MANAGER -- MOVED,
 * 2026-09-01, Aayush's own explicit direction after seeing a reference
 * app's real flow (Home -> facility -> record -> View Details/Pull
 * Records, with View Details showing genuinely parsed clinical content,
 * not raw JSON). An earlier version of this feature lived inside
 * ConsentScreen.tsx's own Level 3 (per that chunk's own original task
 * prompt, which explicitly said not to build a new screen) -- removed
 * from there entirely, not duplicated, once this location was confirmed
 * as the intended one.
 *
 * THE HARD PART THIS MOVE INTRODUCED: Data Flow needs a consentId/hipId/
 * hiuId/date-range to call repo/'s own initiate_health_information_request()
 * (see aegle_phr/phr/data_flow.py's own banner) -- but a Linked Record
 * (spec §9) carries NONE of those; it's a completely different ABDM data
 * model from a Consent artefact (spec §6). extractCoveringConsents()
 * below bridges the two: fetches consent artefacts (#11/
 * GetAllConsentArtefacts, same call ConsentScreen.tsx's own "Approved"
 * tab uses) alongside Linked Records on page load, and maps
 * hip.id -> {consentId, hiuId, dateRange}.
 *
 * WHICH ARTEFACT COUNTS AS "COVERING" -- REWRITTEN (P9, 2026-09-02),
 * REPLACING A REAL BUG: this used to accept ANY GRANTED artefact for a
 * HIP, whoever it was requested by -- meaning a doctor's own consent
 * (about the DOCTOR's own access) and the patient's own ability to view
 * their own linked records could resolve to the exact same artefact.
 * PHR (this screen), HIP (a facility), and HIU (an entity requesting a
 * patient's data) are three genuinely distinct roles in ABDM's model, and
 * that blended them purely because this one sandbox happens to operate
 * all three under one ABDM client -- a real, Aayush-flagged bug ("the
 * consent is mainly for HIU requesting data ... why is there such a
 * confusion being created in the code"), not a design choice. Fixed by
 * filtering strictly on `purpose.code === "PATRQT"` (self-view's own real
 * ABDM purpose code) below, and by this page now RAISING its own
 * dedicated self-view consent automatically (see the provisioning section
 * below) rather than ever reusing whatever else happened to be granted.
 *
 * SELF-VIEW AUTO-PROVISIONING (P9): on load, and again whenever Linked
 * Records changes, this page checks every linked HIP for a covering
 * (PATRQT-GRANTED) consent. If any HIP lacks one AND no PATRQT request is
 * already outstanding from this app, it raises ONE broad self-view
 * request (aegle_phr/phr/data_flow.py's own request_self_view_consent(),
 * covering every linked HIP's own hiType in one call, not one request per
 * facility) and polls briefly for it to auto-grant.
 *
 * THE WORKING ASSUMPTION THIS RESTS ON, NOT YET PROVEN FOR THIS PROJECT'S
 * OWN REGISTRATION -- see data_flow.py's own banner for the full evidence
 * and reasoning: Aayush has observed ABDM's own external sandbox app
 * auto-grant PATRQT requests with no visible approval step, but this has
 * never been confirmed for a PATRQT request raised through THIS project's
 * own HIU registration specifically. If the poll below times out, this is
 * NOT treated as a failure -- the request is simply left exactly where
 * P8's own Requests tab / Approve picker (ConsentScreen.tsx) can act on
 * it, same as any other pending request, and this page shows a plain
 * "waiting for your approval" state rather than an error. Nothing here
 * breaks if the assumption turns out false; it just becomes less
 * automatic, one manual approval instead of zero.
 *
 * AUTO-FETCH (P9): once a HIP has a covering consent -- whether it
 * auto-granted or was manually approved -- its records are pulled
 * automatically (see the auto-fetch effect below), so the patient never
 * needs to click "Pull Records" just to see data behind access that
 * already exists. Manual "Refresh" stays available everywhere Pull
 * Records used to be, for an on-demand re-pull (e.g. after a new visit).
 *
 * A FOREIGN PATRQT CONSENT CAN LOOK LIKE COVERAGE WHEN IT ISN'T --
 * CONFIRMED LIVE, FIXED (P10, 2026-09-02): purpose.code === "PATRQT"
 * alone turned out to be necessary but not sufficient. Consent Manager's
 * artefact list isn't scoped to consents WE raised -- ABDM's own
 * external sandbox app self-grants itself a PATRQT consent on every
 * HIP-Initiated link too (confirmed against real storage/log evidence,
 * 2026-09-02: a Pooja Rameshkumar / Aayush Health Care link produced
 * exactly this), and that artefact is INDISTINGUISHABLE from our own by
 * purpose.code, since both legitimately use the same code for the same
 * reason. Before this fix, extractCoveringConsents() treated that
 * foreign artefact as "covering," so the self-view effect above never
 * even ran -- our own request was never raised, and the only visible
 * symptom was pullRecords() failing with data_flow.py's own "no local
 * record of consent" error forever, with no way to recover on its own.
 * Fixed with two changes, both real, neither cosmetic:
 *   1. pullRecords() below now watches for data_flow.py's own
 *      "consent_not_in_local_cache" reasonCode specifically (a stable,
 *      machine-checkable field added alongside the prose error, NOT a
 *      string-match against text that's free to reword) and records that
 *      consentId into knownBadConsentIds -- state, so it re-triggers the
 *      self-view effect's own coverage check.
 *   2. extractCoveringConsents() now collects EVERY GRANTED PATRQT
 *      candidate per HIP (a HIP can genuinely have more than one once
 *      our own request lands alongside a still-present foreign one) and
 *      picks the first NOT in knownBadConsentIds -- if every candidate
 *      for a HIP is known-bad, that HIP is left out of the map entirely,
 *      so it reads as plain "uncovered," and the self-view effect
 *      raises OUR OWN request for it. The auto-fetch effect's own
 *      dedup guard is keyed by consentId now (not hipKey), specifically
 *      so a HIP whose covering consent CHANGES (foreign, known-bad ->
 *      our own, working) gets auto-fetched again under the new one,
 *      rather than being silently skipped forever because it was
 *      already "tried" once under the old one.
 *
 * P10 STILL WASN'T THE WHOLE STORY -- A SECOND, DEEPER INSTANCE OF THE
 * SAME BUG, CONFIRMED LIVE AND FIXED (P11, 2026-09-02): P10 fixed WHICH
 * artefact gets USED once a HIP has more than one PATRQT candidate --
 * but the self-view effect's own DEDUP CHECK (deciding whether to raise
 * our own request AT ALL) had the identical "purpose.code alone, no
 * check on who raised it" flaw, one level earlier, and P10 never touched
 * it. Confirmed via real evidence, not inference: Pooja Rameshkumar's
 * account got stuck showing "waiting for your approval" indefinitely,
 * and repo/storage/api_capture/m3_*.jsonl -- across EVERY day this
 * project has existed -- has ZERO PATRQT-purposed initiate-consent-
 * request calls for ANY patient. Our own raise had never once actually
 * fired, despite the UI implying an approval was pending. Root cause:
 * ABDM's own external sandbox app's PATRQT self-grant can sit as
 * REQUESTED (not always the near-instant auto-grant observed elsewhere)
 * -- and hasRequested/hasGranted in the self-view effect matched ANY
 * PATRQT entry regardless of requester, so that foreign, not-yet-decided
 * request permanently blocked our own from ever being raised. Doubly
 * broken from the patient's side too: even if that foreign request COULD
 * be approved through this app's own Consent Manager, approving it would
 * grant the FOREIGN app's own registration, not ours -- repo/'s local
 * cache would still never have a row for it, so Home's "Pull Records"
 * could never have started working no matter how long anyone waited or
 * how many times it was approved.
 *
 * FIXED by adding the ONE check P9's own original design note explicitly
 * (and, in hindsight, wrongly) said wasn't needed: requester.name ===
 * SELF_VIEW_REQUESTER_NAME ("Aegle PHR — My Records", must stay
 * byte-for-byte identical to data_flow.py's own request_self_view_consent()
 * literal). That original reasoning was sound for the FETCH-safety
 * question P9/P10 were solving (repo/'s local-cache precondition really
 * does make a foreign artefact unusable regardless of requester.name) --
 * it just didn't cover this EARLIER decision (whether to raise at all),
 * where no such structural safety net exists yet. Applied in two places:
 * the self-view effect's own hasRequested/hasGranted (the actual fix for
 * this bug), and, as a proactive companion to knownBadConsentIds (not a
 * replacement -- see extractCoveringConsents()'s own inline comment),
 * excluding a foreign artefact from candidacy up front instead of only
 * ever discovering it's foreign after one wasted failed pull attempt.
 *
 * P11 WASN'T THE END OF IT EITHER -- A GENUINELY OWN, GENUINELY GRANTED
 * CONSENT STILL COULDN'T BE FETCHED, ROOT CAUSE FOUND LIVE (P12,
 * 2026-09-02): after P11 shipped, self-view requests DID start raising
 * correctly (repo/storage/api_capture/server_2026-09-02.jsonl shows 6
 * separate PATRQT raises for the SAME account this same day, all 202
 * Accepted, all with the correct requester name and hiTypes) -- yet Home
 * kept showing the exact same "waiting for your approval" state. Traced
 * with real evidence, not guessed: every one of those 6 raises got its
 * on-init ack from ABDM correctly (repo/storage/api_capture/m3_*.jsonl,
 * consent_hiu_on_init, ~0.3-0.6s after each raise -- the callback pipeline
 * itself is fine) -- but NOT ONE was ever followed by a consent_hiu_notify
 * callback, the rest of the day, even though notify callbacks for OTHER
 * (third-party, CAREMGT-purposed) requests earlier the same day arrived
 * completely normally. repo/storage/hiu_consents.jsonl confirms the
 * downstream consequence: zero entries for this patient, ever -- repo/'s
 * own fetch_consent() (which the notify callback is what normally
 * triggers automatically) had structurally never been called for any of
 * them. Working theory, NOT a confirmed ABDM spec fact, just what the
 * evidence shows: ABDM's notify webhook exists to tell a THIRD PARTY what
 * a patient decided -- for a PATRQT request, where the "HIU" and the
 * patient's own decision are the same actor, ABDM's real sandbox may
 * simply never fire it.
 *
 * FIXED without needing that callback at all: since Home already learns
 * the moment a PATRQT request becomes GRANTED via its own #4 polling
 * (independent of any callback), pullRecords() below now explicitly
 * calls a NEW backend function -- aegle_phr/phr/data_flow.py's own
 * trigger_consent_fetch(), a thin wrapper over repo/'s own existing
 * fetch_consent() -- the instant a "consent_not_in_local_cache" failure
 * is seen, then retries the SAME pull a few bounded times
 * (FETCH_TRIGGER_MAX_ATTEMPTS x FETCH_TRIGGER_RETRY_INTERVAL_MS = 15s),
 * giving fetch_consent()'s OWN on-fetch callback -- proven working
 * already, e.g. for Aayush's own CAREMGT test consents -- time to land.
 * Only falls through to knownBadConsentIds (P10) if that retry budget is
 * ALSO exhausted, which by then really does mean unrecoverable from here.
 *
 * "PULL RECORDS" IS SCOPED PER-HIP, NOT PER-RECORD, even though the
 * button appears on each record row (matching the reference app's own
 * layout): ABDM's own Health Information Request is date-range/HIP
 * scoped, not single-care-context scoped -- one pull naturally retrieves
 * every care context the covering consent allows for that HIP at once.
 * Tapping Pull Records on ANY record under a HIP triggers the SAME
 * underlying call and populates every other record under that same HIP
 * too, once it completes.
 *
 * "VIEW DETAILS" shows whatever this session has ALREADY pulled for the
 * matching care context (matched by careContextReference against the
 * record's own careContexts[]) -- in-memory only (pullStateByHip below),
 * not persisted across a reload. If nothing's been pulled yet, Level 3
 * shows a plain prompt to go back and pull first, rather than a blank
 * screen or an error.
 *
 * FHIR PARSING -- GROUNDED IN REAL CAPTURED DATA, NOT GENERIC FHIR:
 * every field path below (Condition.code, Observation.component[].
 * valueQuantity, MedicationRequest.medicationCodeableConcept,
 * DiagnosticReport.conclusion, Composition.author/custodian, Encounter.
 * class/period, Patient.name/gender/birthDate) was checked directly
 * against repo/storage/hiu_health_information.jsonl's own real, already-
 * decrypted sandbox content before writing this, not assumed from the
 * FHIR spec generically. Still defensive throughout (a field that isn't
 * there renders as absent, not a crash) since a different HIP's own real
 * data could shape these differently.
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
  ShieldCheck,
  Stethoscope,
  Syringe,
  UserRound,
} from "lucide-react";

import {
  getAllConsentArtefacts,
  getAllConsentRequests,
  discoverSelfViewConsents,
  ensureSelfSubscription,
  ensureSelfViewAutoApprove,
  getAllLinkedRecords,
  getHealthInformationStatus,
  getProfile,
  requestHealthInformation,
  requestSelfViewConsent,
  triggerConsentFetch,
} from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
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
const KNOWN_BAD_CONSENT_IDS_STORAGE_KEY = "aegle.phr.knownBadConsentIds";

function readPersistedBadConsentIds(): Set<string> {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(KNOWN_BAD_CONSENT_IDS_STORAGE_KEY);
    if (raw === null) return new Set();
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.filter((v): v is string => typeof v === "string")) : new Set();
  } catch {
    return new Set();
  }
}

function persistBadConsentIds(ids: Set<string>): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") return;
  try {
    window.localStorage.setItem(KNOWN_BAD_CONSENT_IDS_STORAGE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    /* ignore -- this session still has it in React state either way */
  }
}

/** "2026-08-12T10:15:39.581Z" -> "12-Aug-2026". Falls back to the raw string if it doesn't parse as a date. */
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
 * Bridges Linked Records (spec §9, no consentId at all) to Data Flow
 * (spec §7, needs one) -- see this file's own banner for the full story.
 *
 * REWRITTEN (P9, 2026-09-02), REPLACING the earlier "first GRANTED match
 * per HIP, whoever it was granted to" simplification -- that used to
 * blend a THIRD PARTY's own consent (e.g. a doctor's, about the doctor's
 * own access) with the patient's own self-view, since it accepted ANY
 * GRANTED artefact for a HIP regardless of who requested it. PHR (this
 * screen, the patient viewing their own data), HIP (a facility), and HIU
 * (an entity requesting a patient's data) are three genuinely distinct
 * roles in ABDM's model -- the fact this one sandbox happens to operate
 * all three under one ABDM client must never mean the CODE treats them as
 * interchangeable. Fixed by filtering strictly on
 * `consentDetail.purpose.code === "PATRQT"` -- the spec's own real
 * "Self-Requested" purpose code (confirmed in repo/tools/m3_test_suite/
 * common.py's own purpose table, cross-referenced against a real captured
 * example) -- since P9 now raises self-view under exactly this purpose
 * code (see aegle_phr/phr/data_flow.py's own request_self_view_consent()).
 * No separate `requester.name` check is layered on top -- NOT needed:
 * repo/server/hiu_health_information.py's own precondition
 * (get_hiu_consent(consent_id)) only ever has a row for a consent OUR OWN
 * registration itself raised and fetched, so a PATRQT consent raised by a
 * DIFFERENT app entirely (e.g. ABDM's own external sandbox app) is
 * structurally unusable here regardless of what its requester.name says
 * -- the call would simply fail locally with a clear "no local record"
 * error before ever reaching ABDM. purpose.code alone is therefore
 * sufficient to keep self-view from ever blending with a doctor's/third-
 * party's grant (which uses some OTHER purpose code, e.g. CAREMGT).
 *
 * Same defensive wrapped-or-flat consentDetail handling as
 * ConsentScreen.tsx's own extractArtefactItem(), duplicated here rather
 * than imported per this codebase's own per-screen-helper convention.
 *
 * REWRITTEN AGAIN (P10, 2026-09-02) -- purpose.code === "PATRQT" alone
 * turned out to be NECESSARY but not SUFFICIENT: Consent Manager's own
 * artefact list isn't scoped to consents WE raised, so a PATRQT-GRANTED
 * artefact for a HIP can genuinely belong to a DIFFERENT app/registration
 * entirely (confirmed live, 2026-09-02: ABDM's own external sandbox app
 * self-grants itself PATRQT access on every HIP-Initiated link, same as
 * ours does) -- structurally unusable here (repo/'s own local consent
 * cache will never have a row for it, see data_flow.py's own
 * ConsentNotActiveError/"consent_not_in_local_cache" story), but
 * INDISTINGUISHABLE from our own genuine grant by purpose.code alone,
 * since both use exactly the same code for exactly the same reason. The
 * only way to tell them apart is to have actually TRIED one and watched
 * it fail that specific way -- see knownBadConsentIds below, threaded in
 * from the component so this function can prefer/exclude accordingly.
 *
 * Collects EVERY GRANTED PATRQT candidate per HIP, and returns ALL of
 * them (minus known-bad ones), not just one -- REWRITTEN (2026-09-05)
 * to fix a real bug found live: a single HIP can have SEVERAL separate
 * GRANTED self-view artefacts at once (confirmed against real storage
 * evidence -- ABDM granted one covering all 4 of a patient's linked care
 * contexts at Aayush Health Care, PLUS three more, each covering only a
 * single one of those same 4). The previous version picked just the
 * FIRST usable candidate per HIP and permanently ignored the rest, so
 * whichever candidate came first in ABDM's own artefact list decided how
 * many care contexts were ever actually pulled -- in that real case, a
 * narrow one-care-context artefact happened to be picked, silently
 * capping "Pull Records" at 1 of 4 linked records even though a broader,
 * equally-GRANTED artefact for the same HIP existed unused right next to
 * it. Each ABDM data-flow request only ever returns what ITS OWN consent
 * covers -- there is no single call that unions coverage across several
 * consents -- so the only way to see everything a patient has actually
 * been granted is to pull from every usable candidate and merge the
 * results (see pullRecords()'s own comment for how the merge works).
 * If EVERY candidate for a HIP is known-bad, that HIP is left OUT of the
 * returned map entirely -- deliberately, so it reads as plain "uncovered"
 * everywhere this map is consumed (the self-view effect's own coverage
 * check included), rather than needing every caller to separately know
 * about "covered, but only by something broken."
 */
function extractCoveringConsents(body: unknown, knownBadConsentIds: Set<string>): Map<string, CoveringConsent[]> {
  const candidatesByHip = new Map<string, CoveringConsent[]>();
  if (body === null || typeof body !== "object" || !("consentArtefacts" in body)) return new Map();
  const artefacts = (body as { consentArtefacts: unknown }).consentArtefacts;
  if (!Array.isArray(artefacts)) return new Map();

  for (const item of artefacts) {
    if (item === null || typeof item !== "object") continue;
    if (stringField(item, "status").toUpperCase() !== "GRANTED") continue;
    const wrapped = objField(item, "consentDetail");
    const detail = Object.keys(wrapped).length > 0 ? wrapped : (item as Record<string, unknown>);
    const purpose = objField(detail, "purpose");
    if (purpose.code !== "PATRQT") continue;
    // P11 -- proactive requester check, alongside (not instead of) the
    // reactive knownBadConsentIds backstop above: a foreign app's own
    // PATRQT-GRANTED artefact carries ITS OWN requester.name, not ours
    // (SELF_VIEW_REQUESTER_NAME) -- excluding it here means we never even
    // ATTEMPT a doomed pull against it in the first place, rather than
    // relying solely on watching one fail. Kept as a defensive PAIR, not
    // a replacement: if a real response ever omits requester.name (blank
    // string here), this check can't exclude it, and knownBadConsentIds
    // still catches it after one failed attempt -- same "don't trust a
    // single mechanism" discipline as everywhere else in this file.
    //
    // P13 (2026-09-03) -- SECOND legitimate requester shape, NOT a
    // foreign app: ABDM's own sandbox natively grants self-view under
    // hiu.id "sbx_001" with requester {"name": "SELF", "identifier":
    // {"type": "SELF", ...}} -- confirmed live, real FHIR data
    // successfully pulled and decrypted using one of these. This is
    // NOT "some other app's own competing grant" (the case this guard
    // exists to exclude) -- it's ABDM itself, independent of any app,
    // and data_flow.py's own discover_self_view_consents() (called once
    // per session, see this file's own login effect) registers exactly
    // these with repo/'s local cache so a pull actually succeeds. Before
    // this fix, requester.name here was "SELF", never matched
    // SELF_VIEW_REQUESTER_NAME, so EVERY native grant was silently
    // treated as foreign/uncovered forever -- Home kept re-raising its
    // own request and polling, even once discovery had already made the
    // pull work on the backend, because this frontend check never got a
    // chance to see it as covering in the first place.
    const requester = objField(detail, "requester");
    const requesterIdentifier = objField(requester, "identifier");
    const isOwnRequest = requester.name === SELF_VIEW_REQUESTER_NAME;
    const isNativeSelfGrant = requester.name === "SELF" || requesterIdentifier.type === "SELF";
    if (!isOwnRequest && !isNativeSelfGrant) continue;
    const hip = objField(detail, "hip");
    const hiu = objField(detail, "hiu");
    const permission = objField(detail, "permission");
    const dateRange = objField(permission, "dateRange");
    const hipId = typeof hip.id === "string" ? hip.id : "";
    if (hipId === "") continue;
    const consentId = typeof detail.consentId === "string" ? detail.consentId : typeof detail.requestId === "string" ? detail.requestId : "";
    if (consentId === "") continue;
    const candidate: CoveringConsent = {
      consentId,
      hipId,
      hiuId: typeof hiu.id === "string" ? hiu.id : "",
      periodFrom: typeof dateRange.from === "string" ? dateRange.from : "",
      periodTo: typeof dateRange.to === "string" ? dateRange.to : "",
    };
    const existing = candidatesByHip.get(hipId);
    if (existing) existing.push(candidate);
    else candidatesByHip.set(hipId, [candidate]);
  }

  const map = new Map<string, CoveringConsent[]>();
  for (const [hipId, candidates] of candidatesByHip) {
    const usable = candidates.filter((c) => !knownBadConsentIds.has(c.consentId));
    if (usable.length > 0) map.set(hipId, usable);
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
const SELF_VIEW_REQUESTER_NAME = "Aegle PHR — My Records";

interface ConsentRequestPurposeStatus {
  status: string;
  purposeCode: string;
  requesterName: string;
}

/** Minimal reader over #4's own requests[] -- only what the dedup check below needs (status + purpose.code + requester.name, the last one added P11 -- see SELF_VIEW_REQUESTER_NAME's own docstring), not the full ConsentRequestSummary ConsentScreen.tsx builds (duplicated per-screen-helper convention, same as everything else in this file). */
function extractConsentRequestPurposeStatuses(body: unknown): ConsentRequestPurposeStatus[] | null {
  if (body === null || typeof body !== "object" || !("requests" in body)) return null;
  const requests = (body as { requests: unknown }).requests;
  if (!Array.isArray(requests)) return null;
  const out: ConsentRequestPurposeStatus[] = [];
  for (const item of requests) {
    if (item === null || typeof item !== "object") continue;
    const purpose = objField(item, "purpose");
    const requester = objField(item, "requester");
    out.push({
      status: stringField(item, "status"),
      purposeCode: typeof purpose.code === "string" ? purpose.code : "",
      requesterName: typeof requester.name === "string" ? requester.name : "",
    });
  }
  return out;
}

type SelfViewPhase = "idle" | "checking" | "raising" | "polling" | "pending_approval" | "granted" | "error";

interface SelfViewState {
  phase: SelfViewPhase;
  message: string;
}

const SELF_VIEW_IDLE: SelfViewState = { phase: "idle", message: "" };

/**
 * "A few attempts, clear timeout" -- same convention as Data Flow's own
 * POLL_MAX_ATTEMPTS/POLL_INTERVAL_MS above, deliberately a SHORTER budget
 * here: this is polling for a status word to flip (ABDM/CM-side), not
 * waiting on a HIP's own data push, and the working assumption's own
 * evidence point (an externally-raised PATRQT notify observed arriving
 * "GRANTED" about ONE second after the triggering UIL confirm) suggests
 * this should resolve fast if it resolves automatically at all -- 20s
 * gives generous margin above that single data point while still failing
 * into the manual-approval fallback quickly if the assumption is wrong
 * for this project's own registration, rather than making every login
 * wait a long time to find out.
 */
const SELF_VIEW_POLL_INTERVAL_MS = 2000;
const SELF_VIEW_POLL_MAX_ATTEMPTS = 10;

/** Broad default hiTypes for the self-view request when no linked record carries an hiType at all (a genuinely empty request would ask ABDM for nothing) -- same literal list ConsentScreen.tsx's own Auto-Approve section already offers as choices. */
const SELF_VIEW_DEFAULT_HI_TYPES = [
  "Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
  "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
];

/**
 * P9 item 3 -- "a HIP that's linked but NOT yet covered ... should show
 * its own clear state, not an error and not a blank Fetch Record button
 * pretending nothing is happening." Reads the SAME selfViewState the
 * provisioning effect above drives, so the message here always matches
 * what's actually happening (checking/raising/polling/waiting-on-you),
 * rather than a generic "no access" callout unrelated to what's really
 * going on for this HIP.
 */
function SelfViewWaitingCallout({ state }: { state: SelfViewState }): JSX.Element {
  if (state.phase === "pending_approval") {
    return (
      <Callout tone="warning" icon={ShieldCheck}>
        <p style={{ margin: 0 }}>{state.message}</p>
        <ButtonLink variant="secondary" size="sm" icon={ShieldCheck} to="/consent">Open Consent Manager</ButtonLink>
      </Callout>
    );
  }
  if (state.phase === "error") {
    return <Callout tone="warning">{state.message}</Callout>;
  }
  if (state.phase === "checking" || state.phase === "raising" || state.phase === "polling") {
    return <Callout>{state.message}</Callout>;
  }
  return <Callout>Waiting for access to this facility's records — checking shortly.</Callout>;
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
  const [selfViewState, setSelfViewState] = useState<SelfViewState>(SELF_VIEW_IDLE);
  const selfViewRunningRef = useRef(false);
  const autoFetchTriggeredRef = useRef<Set<string>>(new Set());
  /** P11 -- true once ensureSelfViewAutoApprove() has been ATTEMPTED this session (regardless of outcome) -- a ref, not state, so it survives re-renders without itself triggering one, and so it's checked/set synchronously (no risk of two overlapping effect runs both deciding to call it). Deliberately "attempted," not "succeeded": a failure here must not block the existing raise-then-manual-approve fallback (see the self-view effect's own comment at the call site), so this is set true right after the one call, whichever way it went. */
  const autoApproveEnsuredRef = useRef(false);
  /**
   * P10 -- consent ids confirmed NOT locally fetchable by us, populated
   * the moment pullRecords() below gets back data_flow.py's own
   * "consent_not_in_local_cache" reasonCode. React state (not a ref):
   * this must trigger a re-render (and, via the self-view effect's own
   * dependency array, a re-check of whether any HIP is now genuinely
   * uncovered) the moment a candidate is confirmed bad -- a ref update
   * alone wouldn't do either. See extractCoveringConsents()'s own banner
   * for exactly how this gets used to pick between multiple candidates.
   *
   * P14 -- initialized from localStorage, not always empty -- see
   * readPersistedBadConsentIds()'s own docstring for why a fresh page
   * load must not forget a consent already proven permanently dead.
   */
  const [knownBadConsentIds, setKnownBadConsentIds] = useState<Set<string>>(() => readPersistedBadConsentIds());

  /** Adds one consentId to knownBadConsentIds AND persists it -- the one place either ever happens, so the two can never drift apart. See readPersistedBadConsentIds()'s own docstring. */
  const markConsentBad = (consentId: string): void => {
    setKnownBadConsentIds((prev) => {
      if (prev.has(consentId)) return prev;
      const next = new Set(prev);
      next.add(consentId);
      persistBadConsentIds(next);
      return next;
    });
  };

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
    // P13 -- ABDM appears to grant self-view (PATRQT) access natively, on
    // its own, independent of anything raised through this app's own
    // registration (confirmed live: hiu.id "sbx_001", requester "SELF").
    // extractCoveringConsents() below already sees these as "covered"
    // (they're real GRANTED artefacts from #9's own list), so the self-
    // view auto-provisioning effect further down correctly never tries
    // to raise a redundant request for them -- but a GRANTED artefact
    // ABDM shows us isn't the same as one this app's own registration can
    // actually PULL DATA for: repo/'s hiu_consent_repository only ever
    // learns about a consent via ABDM's own HIU-directed notify callback,
    // which "sbx_001" almost certainly never triggers (it isn't a HIU
    // this bridge is registered as). Without that local record, Pull
    // Records fails with reasonCode "consent_not_in_local_cache" the
    // moment someone actually clicks it, even though the artefact looked
    // fine the whole time. Firing this here, once per session alongside
    // the other three sibling calls, closes that gap proactively instead
    // of waiting for a failed pull to surface it -- same fire-and-forget
    // convention as ensureSelfViewAutoApprove()'s own call below (outcome
    // not branched on; failures surface through the Console panel like
    // every other apiRequest() call already does). The actual local
    // registration still lands moments later via ABDM's own on-fetch
    // callback -- see data_flow.py's own discover_self_view_consents()
    // docstring for the full async chain this kicks off.
    void discoverSelfViewConsents({ xToken: sessionToken });

    // P13 -- the subscription-equivalent of the auto-approve call two
    // lines below: spec §8.1's own auto-approve claim for Subscriptions,
    // set up once per session alongside consent auto-approve and
    // discovery, so all three self-service policies get established in
    // the same pass. No xToken needed (see ensureSelfSubscription()'s own
    // docstring -- a REQUESTER-role call) -- fire-and-forget, same
    // convention as its two siblings here (failure surfaces via the
    // Console panel, never blocks anything else on this page).
    if (sessionAddress !== "") void ensureSelfSubscription({ patientAbhaAddress: sessionAddress });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionToken]);

  const linkedRecords = extractLinkedRecords(linksResult?.data?.body ?? null);
  const coveringConsents = extractCoveringConsents(consentArtefactsResult?.data?.body ?? null, knownBadConsentIds);

  /**
   * P9 -- self-view auto-provisioning. Re-runs whenever Linked Records or
   * the covering-consent artefacts actually change identity (a fresh
   * fetch resolving) -- deliberately NOT keyed on the derived
   * linkedRecords/coveringConsents values themselves, which are new
   * object/array/Map instances on every render and would re-fire this
   * effect every render rather than only on a real data change.
   * selfViewRunningRef guards against overlapping runs (e.g. a manual
   * "Refresh" landing mid-poll) -- a ref rather than state since it must
   * be checked synchronously, not after a state commit.
   *
   * P10 -- ALSO re-runs when knownBadConsentIds changes: a HIP that
   * looked "covered" a moment ago (a foreign PATRQT-GRANTED artefact,
   * indistinguishable from our own by purpose.code alone) can turn out
   * to be genuinely uncovered the instant pullRecords() confirms that
   * consentId isn't fetchable by us -- this effect needs a chance to
   * notice that and actually raise our own request, which is exactly
   * the bug this pass fixes (see extractCoveringConsents()'s own banner).
   */
  useEffect(() => {
    if (sessionToken === "" || linksResult === null || consentArtefactsResult === null) return;
    if (selfViewRunningRef.current) return;

    const records = extractLinkedRecords(linksResult.data?.body ?? null);
    if (records === null || records.length === 0) return;

    const covering = extractCoveringConsents(consentArtefactsResult.data?.body ?? null, knownBadConsentIds);
    const anyUncoveredHip = groupByHip(records).some((group) => !covering.has(group.key));
    if (!anyUncoveredHip) {
      setSelfViewState((prev) => (prev.phase === "idle" ? prev : SELF_VIEW_IDLE));
      return;
    }

    selfViewRunningRef.current = true;
    void (async () => {
      try {
        setSelfViewState({ phase: "checking", message: "Checking for existing self-view access…" });

        const requestsResult = await getAllConsentRequests({ xToken: sessionToken });
        const requests = extractConsentRequestPurposeStatuses(requestsResult.data?.body ?? null) ?? [];
        // P11 -- requesterName === SELF_VIEW_REQUESTER_NAME, NOT purpose.code
        // alone. Confirmed live, 2026-09-02 (Pooja Rameshkumar's account):
        // ABDM's own external sandbox app raises its OWN PATRQT self-grant
        // on every HIP-Initiated link, same as ours does. purpose.code
        // alone can't tell the two apart, so without this check a foreign
        // app's own pending (or granted) PATRQT request permanently blocks
        // OUR OWN from ever being raised -- the patient gets stuck on
        // "pending_approval" forever, waiting on a request that (a) isn't
        // ours, and (b) even if approved, would grant access to the
        // FOREIGN app's own registration, not ours -- so it could never
        // actually fix Home's own "Pull Records," no matter how long
        // anyone waits or how many times it's approved. See this file's
        // own banner for the confirmed evidence trail (repo/storage/
        // api_capture/m3_*.jsonl has zero PATRQT-purposed
        // initiate-consent-request calls, ever, for any patient -- our own
        // raise had never actually fired, despite the UI showing "waiting
        // for approval").
        const ours = requests.filter((r) => r.purposeCode === "PATRQT" && r.requesterName === SELF_VIEW_REQUESTER_NAME);
        const hasRequested = ours.some((r) => r.status.toUpperCase() === "REQUESTED");
        const hasGranted = ours.some((r) => r.status.toUpperCase() === "GRANTED");

        if (hasRequested) {
          // Dedup: a self-view request from this app is already outstanding --
          // don't raise a second one. Fallback path, P8's own Approve picker.
          setSelfViewState({ phase: "pending_approval", message: "Waiting for your approval in Consent Manager to view some of your linked records." });
          return;
        }
        if (hasGranted) {
          // A PATRQT request exists and was decided, but doesn't cover every
          // linked HIP (ABDM/the patient resolved it to fewer facilities than
          // are actually linked) -- accepted per this pass's own scope: one
          // broad request, not re-raised just because it didn't end up
          // covering everything.
          setSelfViewState(SELF_VIEW_IDLE);
          return;
        }

        // P11 -- set up ABDM's real Consent Auto-Approval standing policy
        // for self-view ONCE per session, before the FIRST raise -- root
        // cause of P9/P10's own residual failure (confirmed against real
        // repo/storage evidence): our own self-view requests were being
        // raised and on-init-acked correctly, but never approved by
        // anyone, ever, so they just sat REQUESTED forever. This is what's
        // supposed to make a request raised AFTER it auto-grant instead.
        // A FAILURE HERE MUST NOT BLOCK THE EXISTING FALLBACK -- if setup
        // fails, self-view degrades to exactly what it already did before
        // this pass (raise, then sit REQUESTED, approvable through P8's
        // own picker), not a hard failure. autoApproveEnsuredRef is set
        // true regardless of outcome so this is only ever ATTEMPTED once
        // per session, not retried on every HIP/every effect run.
        if (!autoApproveEnsuredRef.current) {
          autoApproveEnsuredRef.current = true;
          setSelfViewState({ phase: "checking", message: "Setting up automatic access to your own records…" });
          // Outcome deliberately not branched on beyond this -- a failure
          // here already surfaces through the app's own Console panel
          // (every apiRequest() call is recorded there regardless), and
          // per this effect's own comment above, self-view must proceed
          // to raise the request either way, not stop here.
          await ensureSelfViewAutoApprove({ xToken: sessionToken });
        }

        // No PATRQT request exists at all yet -- raise one, broad across
        // every linked HIP's own hiType (not per-HIP, see data_flow.py's
        // own request_self_view_consent() docstring).
        const hiTypesSet = new Set(records.map((r) => r.hiType).filter((h) => h !== ""));
        const hiTypes = hiTypesSet.size > 0 ? Array.from(hiTypesSet) : SELF_VIEW_DEFAULT_HI_TYPES;
        const now = new Date();
        const dateRangeFrom = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000).toISOString();
        const dateRangeTo = now.toISOString();

        setSelfViewState({ phase: "raising", message: "Requesting access to view your own linked records…" });
        const raised = await requestSelfViewConsent({ hiTypes, dateRangeFrom, dateRangeTo, patientAbhaAddress: sessionAddress });
        if (raised.data?.ok !== true) {
          setSelfViewState({ phase: "error", message: raised.data?.error || "Couldn't request self-view access — check the Console for details." });
          return;
        }

        // Polls #4 for the request WE just raised to flip to GRANTED --
        // identified by purpose.code alone (PATRQT is exclusive to self-
        // view now), not a captured id -- see data_flow.py's own docstring
        // for why request_self_view_consent() can't hand one back anyway.
        setSelfViewState({ phase: "polling", message: "Requesting access to view your own linked records…" });
        for (let attempt = 0; attempt < SELF_VIEW_POLL_MAX_ATTEMPTS; attempt += 1) {
          await sleep(SELF_VIEW_POLL_INTERVAL_MS);
          const pollResult = await getAllConsentRequests({ xToken: sessionToken });
          const polled = extractConsentRequestPurposeStatuses(pollResult.data?.body ?? null) ?? [];
          const grantedNow = polled.some((r) => r.purposeCode === "PATRQT" && r.status.toUpperCase() === "GRANTED");
          if (grantedNow) {
            setSelfViewState({ phase: "granted", message: "Access granted." });
            // Refreshes coveringConsents so the newly-GRANTED PATRQT
            // artefact(s) show up -- the auto-fetch effect below reacts to
            // that and pulls the newly-covered HIP(s) automatically.
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
            return;
          }
        }

        // WORKING ASSUMPTION WAS WRONG (or just slow) FOR THIS REQUEST --
        // not a failure. Leaves it exactly where P8's own Requests tab/
        // Approve picker can act on it, same as any other pending request.
        setSelfViewState({ phase: "pending_approval", message: "Waiting for your approval in Consent Manager to view some of your linked records." });
      } finally {
        selfViewRunningRef.current = false;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionToken, linksResult, consentArtefactsResult, knownBadConsentIds]);

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
    // P14 -- a genuine timeout (POLL_MAX_ATTEMPTS x POLL_INTERVAL_MS, 90s --
    // generous) means the HIP never pushed anything for this consent's own
    // care context(s), confirmed live for consents pointing at old/
    // regenerated test data that no longer exists on the HIP side. See
    // markConsentBad()/readPersistedBadConsentIds()'s own docstring for why
    // this must be persisted, not just noted for this render.
    markConsentBad(consentId);
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
      // lets the self-view effect notice this HIP is actually
      // uncovered and raise our OWN fresh request for it, instead of
      // silently trusting a consent that can never work and stopping
      // there forever. Only THIS one consent is affected -- any other
      // covering consent for the same HIP keeps pulling independently.
      if (requestResult.data?.reasonCode === "consent_not_in_local_cache") {
        markConsentBad(covering.consentId);
      }
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
          <SelfViewWaitingCallout state={selfViewState} />
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

        {!coveringConsents.has(selectedHip.key) && <SelfViewWaitingCallout state={selfViewState} />}
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
