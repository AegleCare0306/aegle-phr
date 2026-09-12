/**
 * Consent Manager -- all 11 patient-facing consent flows (spec §6.13-
 * §6.22, plus Approve, Postman-only -- see the backend's aegle_phr/phr/
 * consent.py for the full story). Lets a patient control who gets to
 * READ the data behind the care contexts HomeScreen.tsx's own "Linked
 * Records" section shows -- this screen does NOT itself fetch any
 * health-record content (spec §7 "Data Flow", a separate, later phase).
 *
 * THREE-LEVEL DRILL-DOWN, matching a real reference design Aayush shared
 * directly rather than a flat expand/collapse-per-endpoint layout (an
 * earlier version of this screen just listed raw fields per endpoint --
 * correct data, but "not organized, just displayed for the sake of
 * displaying," per his own words):
 *
 *   Level 1 -- "Requests" tab: one card per REQUEST (#4/
 *   GetAllConsentRequests), the requester's name as the heading, filterable
 *   by status chips (All/Pending/Granted/Denied/Expired/Revoked -- "Pending"
 *   is this screen's own label for ABDM's own status STRING "REQUESTED",
 *   confirmed live 2026-09-01 alongside "REVOKED"; the other three are the
 *   spec's own literal status names), client-side over the one fetched
 *   list -- #4 already returns every request's own `status`, no need for a
 *   separate call per filter.
 *
 *   Level 2 -- tap "View details" on a request: if it's already been
 *   decided (status GRANTED), fetch #9 (GetConsentArtefactsByRequest) --
 *   an ARRAY, one entry per HIP, because a single request can be approved
 *   against several HIPs and each produces its own artefact. THIS is what
 *   #9's own array shape is FOR -- confirmed by Aayush's own reference
 *   screenshots showing exactly this (one doctor's request expanding into
 *   several HIP-named cards). For any OTHER status (REQUESTED still open,
 *   or a terminal DENIED/EXPIRED/REVOKED), fetch #5 (GetConsentRequestDetails)
 *   instead -- a LIVE capture (Aayush, 2026-09-01, a REVOKED request) showed
 *   #5's own response is shaped like a REQUEST (requestId/status/purpose/
 *   patient/hiu/requester/hiTypes/permission), the SAME shape as one #4
 *   item, NOT hip/careContexts-shaped like an artefact -- a request only
 *   gets tied to one HIP once GRANTED and split into artefacts. An earlier
 *   version of this file wrongly assumed #5 was artefact-shaped and tried
 *   reading hip.id off it for every non-GRANTED status, which is what broke
 *   "View details" on anything that wasn't still open (REVOKED included)
 *   with a confusing "missing hip.id" message. Only a REQUESTED status now
 *   shows Deny; anything terminal shows a plain read-only detail card.
 *
 *   Level 3 -- tap "View details" again on one HIP-level card: the full
 *   breakdown for that one artefact -- information type (hiTypes),
 *   request duration, consent valid-upto (dataEraseAt), and "you have
 *   given access to" (that HIP's own care contexts, listed under it).
 *   Revoke (#8) lives here and on the Level-2 card.
 *
 * "Approved" tab (#11/GetAllConsentArtefacts) is a SEPARATE, flat list of
 * every currently-active grant regardless of which request produced it --
 * grouped by requester (groupByRequester() below, same pattern as
 * HomeScreen.tsx's own groupByHip()) since one requester can appear via
 * multiple HIPs here too. Tapping a card goes straight to the SAME Level-3
 * detail view Level 2 uses -- one artefact, one shape, one renderer.
 *
 * VISUAL REDESIGN (design-overhaul chunk, 2026-09-01): status chips/badges
 * now route through the shared Badge component (icon + color pair, not
 * just colored text), request/artefact cards render inside CardGrid so a
 * row of them is actually even-sized, and the disabled-Approve explanation
 * below is a Callout (icon + text in a bordered box) instead of a
 * permanently-disabled gray button -- a button that can never be clicked
 * is confusing UI, the explanation alone says what's going on. Nothing in
 * this pass touches which endpoint is called, when, or with what body.
 *
 * APPROVE -- WIRED UP (P8, 2026-09-02). The original plan was "full-
 * acceptance-only" (submit exactly what the request named, no narrowing),
 * but #5's own confirmed live shape (see below) never carries a hip/
 * careContexts to submit in the first place -- there was nothing to accept
 * as-is. Fixed with a HIP + care-context picker, sourced from a SEPARATE
 * fetch of Linked Records (spec §9, same endpoint HomeScreen.tsx's own
 * "Linked Records" section uses -- an independent fetch here rather than
 * lifted/shared state, since the two screens are separately-mounted routes
 * with no shared parent state, and this app already re-fetches the same
 * endpoints from multiple screens elsewhere). CONFIRMED LIVE (this pass):
 * a Linked Record's own item DOES carry an hiType field, so the picker IS
 * filtered to the request's own wanted hiTypes, not shown unfiltered.
 * hiTypes/permission are still submitted UNCHANGED from the request's own
 * values (the original plan's one part that was always fine) -- only WHICH
 * HIP(s)/care context(s) is an actual choice now. `permission` is read
 * from pendingDetail (#5's own freshly-fetched per-request detail), not
 * the Level-1 list item, since #5 is this screen's authoritative per-
 * request source.
 *
 * KNOWN, FLAGGED GAP LEFT IN THE APPROVE SUBMISSION: ConsentGrant's own
 * required shape needs BOTH patientReference and careContextReference per
 * care context, but spec §9.3.5's own documented Linked-Records shape (and
 * its backend pydantic model, links.py's LinkedCareContext) never declares
 * a patientReference field at all -- confirmed by reading that model
 * directly, not assumed. extractPickerRecords() below reads it
 * defensively anyway (in case a real response carries it despite not
 * being documented -- this backend never strips undeclared fields) and
 * falls back to whatever an EXISTING granted artefact for the same HIP
 * already has (same patient+HIP, so it should be stable) via a second,
 * separate #11 fetch. If NEITHER source has it for a given HIP, it is
 * submitted as "" -- UNCONFIRMED whether ABDM's own approve endpoint
 * accepts that or rejects it; this could NOT be settled without a live
 * call (no ABDM sandbox session was available to this pass -- see this
 * project's own verification notes). Aayush's own live Approve test is
 * what actually confirms or breaks this.
 *
 * REVOKE'S OWN "consentId" -- CORRECTED, cross-referenced against real
 * data during the Data Flow chunk (2026-09-01): the field is
 * consentDetail.consentId, NOT consentDetail.requestId (the previous
 * guess here). Confirmed via repo/server/callbacks/services/
 * consent_hiu_on_fetch_service.py's own docstring -- "a real captured
 * Postman example, matching field-for-field" -- which stores a fetched
 * consent artefact keyed by exactly this field
 * (consent.consentDetail.consentId), and cross-checked against
 * repo/storage/hiu_consents.jsonl's own real stored record for the same
 * consent this project has been testing against all along: its
 * consentId ("d965e250-...") and its requestId ("9a8c276b-...", visible
 * in this same consent's own raw response pasted into this project
 * earlier) are two DIFFERENT values -- so the old requestId-based guess
 * was concretely wrong, not just unconfirmed. extractArtefactItem() below
 * now reads consentId first, falling back to requestId only if consentId
 * is ever absent from a real response (still defensive, just correctly
 * ordered now).
 *
 * ARTEFACT SHAPE (#9/#11) -- STILL UNCONFIRMED, NOT SETTLED THIS PASS:
 * P8's own task prompt asked for this to be checked against a real live
 * #11 call -- not possible this pass (no ABDM sandbox session/credentials
 * or logged-in browser session were available to check it directly; see
 * this project's own verification notes for what WAS and wasn't checked).
 * What's true either way: extractArtefactItem() below tries the spec's own
 * documented wrapped shape ({status, consentDetail: {...}, signature})
 * first and falls back to treating the item itself as the detail object --
 * and this dual check is FUNCTIONALLY correct for either shape already
 * (if wrapped, `item.consentDetail` is non-empty and gets used; if flat,
 * it's absent/empty and the code falls through to the item itself) -- so
 * "which shape ABDM actually returns" doesn't change behavior today, only
 * confidence in the docstring. Reordering which is "tried first" was
 * considered but NOT done, since there's no live #9/#11 evidence (as
 * opposed to the sibling #5 endpoint, which WAS confirmed live flat) to
 * base a reorder on -- guessing an order from a different endpoint's
 * result isn't the "evidence-based, not a guess" bar this was asked to
 * clear. Aayush's own live check against a real GRANTED consent's #11
 * response is what actually settles this -- see this project's own
 * verification notes for exactly what to look at.
 *
 * AUTO-APPROVE'S OWN "consentId" for enable/disable -- STILL A GENUINE SPEC
 * GAP, IMPROVED WHERE POSSIBLE (P8, 2026-09-02): §6.13's own response is
 * undocumented everywhere checked (spec PDF and Postman both) -- 202
 * Accepted, no body -- so how a caller is meant to LEARN the consentId
 * that §6.14/§6.15 need to act on is genuinely unclear, and this was NOT
 * something a live call could settle this pass either (same access gap as
 * the artefact-shape item above). What WAS improved: the manual field's
 * own copy now says plainly what's needed (an existing GRANTED consent's
 * own consentId, findable in the "Approved" tab / Level 3) instead of just
 * "type one in manually," and it self-prefills from the last artefact the
 * patient actually viewed at Level 3, when reached that way -- a real,
 * if small, UX improvement even though the underlying spec gap itself
 * can't be closed from this side.
 *
 * DATA FLOW (spec §7, "Fetch my records") DOES NOT LIVE HERE -- MOVED,
 * 2026-09-01: an earlier version of this chunk added a "Fetch my
 * records" section at the bottom of Level 3, per that chunk's own
 * original task prompt (which explicitly said not to build Data Flow
 * its own screen). Aayush later shared a reference app whose own real
 * flow puts this on the Home / Linked Records screen instead (facility
 * -> individual record -> View Details/Pull Records, with View Details
 * showing genuinely parsed clinical content) -- see HomeScreen.tsx's own
 * banner for the full story and why that needed bridging Linked Records
 * (spec §9, no consentId) to Consent artefacts (spec §6, has one) to
 * work at all. Removed entirely from here rather than duplicated.
 *
 * Every parser below is defensive and falls back to the shared RawBody
 * dump rather than silently showing nothing when a real response doesn't
 * match what's documented.
 */

import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowLeft,
  Ban,
  Building2,
  CalendarClock,
  Check,
  CheckCircle2,
  Clock,
  Eye,
  FileText,
  Hourglass,
  Inbox,
  RefreshCw,
  Send,
  ShieldCheck,
  User,
  X,
  XCircle,
} from "lucide-react";

import {
  approveConsentRequest,
  autoApprove,
  denyConsentRequest,
  discoverSelfViewConsents,
  disableAutoApprove,
  enableAutoApprove,
  getAllConsentArtefacts,
  getAllConsentRequests,
  getAllLinkedRecords,
  getConsentArtefactsByRequest,
  getConsentRequestDetails,
  revokeConsents,
} from "../api/endpoints";
import type { ConsentGrant } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import type { BadgeTone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardFooter, CardTitle } from "../components/ui/Card";
import { CardGrid } from "../components/ui/CardGrid";
import { Callout } from "../components/ui/Callout";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { getSessionToken } from "../session";

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

/** "2026-08-12T10:15:39.581Z" -> "12-Aug-2026". Falls back to the raw string if it doesn't parse as a date. */
function formatDate(iso: string): string {
  if (iso === "") return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }).replace(/ /g, "-");
}

const HI_TYPES = [
  "Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
  "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
] as const;

const STATUS_FILTERS = ["ALL", "REQUESTED", "GRANTED", "DENIED", "EXPIRED", "REVOKED"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

function statusFilterLabel(filter: StatusFilter): string {
  if (filter === "ALL") return "All";
  if (filter === "REQUESTED") return "Pending";
  return filter.charAt(0) + filter.slice(1).toLowerCase();
}

/** Icon + color pair per status -- so a status reads as intentional, not just colored text. */
function statusBadge(status: string): { tone: BadgeTone; icon: LucideIcon; label: string } {
  const upper = status.toUpperCase();
  if (upper === "GRANTED") return { tone: "success", icon: CheckCircle2, label: status };
  if (upper === "REQUESTED") return { tone: "warning", icon: Clock, label: "Pending" };
  if (upper === "DENIED") return { tone: "danger", icon: XCircle, label: status };
  if (upper === "EXPIRED") return { tone: "neutral", icon: Hourglass, label: status };
  if (upper === "REVOKED") return { tone: "danger", icon: Ban, label: status };
  return { tone: "neutral", icon: Clock, label: status || "Unknown status" };
}

// --- Level 1: consent requests, and #5's own single-request detail ------

interface ConsentRequestSummary {
  requestId: string;
  requesterName: string;
  status: string;
  purposeText: string;
  periodFrom: string;
  periodTo: string;
  hiTypes: string[];
  dataEraseAt: string;
}

/**
 * Shared reader for one request-shaped object -- used for each item of #4's
 * own `requests[]` AND for #5's own single-object response, since a LIVE
 * capture (Aayush, 2026-09-01, a REVOKED request) confirmed #5 returns the
 * SAME shape as a #4 item (requestId/status/purpose/patient/hiu/requester/
 * hiTypes/permission), NOT hip/careContexts-shaped like an artefact. A
 * request only gets tied to a specific HIP once GRANTED and split into
 * artefacts (#9) -- see extractArtefactItem() below. This corrects an
 * earlier version of this file that assumed #5 was artefact-shaped and
 * tried to read hip.id off it -- confirmed live to never be there, which
 * is what broke "View details" on every non-GRANTED request, not just
 * revoked ones.
 */
function extractRequestSummary(item: unknown): ConsentRequestSummary | null {
  if (item === null || typeof item !== "object") return null;
  const requester = objField(item, "requester");
  const hiu = objField(item, "hiu");
  const purpose = objField(item, "purpose");
  const permission = objField(item, "permission");
  const dateRange = objField(permission, "dateRange");
  const hiTypesRaw = (item as Record<string, unknown>).hiTypes;
  return {
    requestId: stringField(item, "requestId"),
    requesterName: (typeof requester.name === "string" && requester.name) || (typeof hiu.name === "string" ? hiu.name : "") || (typeof hiu.id === "string" ? hiu.id : ""),
    status: stringField(item, "status"),
    purposeText: typeof purpose.text === "string" ? purpose.text : "",
    periodFrom: typeof dateRange.from === "string" ? dateRange.from : "",
    periodTo: typeof dateRange.to === "string" ? dateRange.to : "",
    hiTypes: Array.isArray(hiTypesRaw) ? hiTypesRaw.filter((h): h is string => typeof h === "string") : [],
    dataEraseAt: typeof permission.dataEraseAt === "string" ? permission.dataEraseAt : "",
  };
}

function extractConsentRequests(body: unknown): ConsentRequestSummary[] | null {
  if (body === null || typeof body !== "object" || !("requests" in body)) return null;
  const requests = (body as { requests: unknown }).requests;
  if (!Array.isArray(requests)) return null;
  const out: ConsentRequestSummary[] = [];
  for (const item of requests) {
    const parsed = extractRequestSummary(item);
    if (parsed !== null) out.push(parsed);
  }
  return out;
}

/** #5's own response is a single object in the same shape as one #4 item -- see extractRequestSummary()'s own comment. */
function extractRequestDetail(body: unknown): ConsentRequestSummary | null {
  return extractRequestSummary(body);
}

// --- Levels 2/3: consent artefacts (one per HIP) ------------------------

interface ConsentCareContextItem {
  patientReference: string;
  careContextReference: string;
}

interface ConsentArtefactDetail {
  status: string;
  requesterName: string;
  hipName: string;
  /** hip.id -- needed (alongside hiuId/consentId/the date range) for Data Flow's "Fetch my records" (spec §7), not just display. */
  hipId: string;
  /** hiu.id -- this project's own HIU identity, as recorded on the artefact itself. Needed for Data Flow. */
  hiuId: string;
  purposeText: string;
  hiTypes: string[];
  periodFrom: string;
  periodTo: string;
  dataEraseAt: string;
  careContexts: ConsentCareContextItem[];
  /** consentDetail.consentId -- confirmed against repo/'s own real stored data, see this file's own banner. Falls back to requestId only if a real response ever lacks consentId. */
  consentId: string;
}

/**
 * Shared per-item reader for #9's bare array AND #11's wrapped
 * consentArtefacts[] -- the spec's own documented shape is {status,
 * consentDetail: {...}, signature}, but a LIVE capture of the sibling #5
 * endpoint (Aayush, 2026-09-01) confirmed ABDM sometimes skips this kind
 * of wrapper entirely and returns the detail fields flat on the item
 * itself. Tries the wrapped shape first, falls back to treating the item
 * itself as the detail object -- if #9/#11 turn out to be flat the same
 * way #5 was, this is what was silently emptying the "My Active Consents"
 * / per-request artefact lists (no parsed items -> no Revoke button to
 * click at all, not a revoke-call failure).
 */
function extractArtefactItem(item: unknown): ConsentArtefactDetail | null {
  if (item === null || typeof item !== "object") return null;
  const wrapped = objField(item, "consentDetail");
  const detail = Object.keys(wrapped).length > 0 ? wrapped : (item as Record<string, unknown>);
  const hip = objField(detail, "hip");
  const purpose = objField(detail, "purpose");
  const requester = objField(detail, "requester");
  const hiu = objField(detail, "hiu");
  const permission = objField(detail, "permission");
  const dateRange = objField(permission, "dateRange");
  const hiType = detail.hiType ?? detail.hiTypes;
  const rawCareContexts = detail.careContexts;
  const careContexts: ConsentCareContextItem[] = Array.isArray(rawCareContexts)
    ? rawCareContexts
        .filter((cc): cc is Record<string, unknown> => cc !== null && typeof cc === "object")
        .map((cc) => ({
          patientReference: typeof cc.patientReference === "string" ? cc.patientReference : "",
          careContextReference: typeof cc.careContextReference === "string" ? cc.careContextReference : "",
        }))
    : [];
  return {
    status: stringField(item, "status"),
    requesterName: (typeof requester.name === "string" && requester.name) || (typeof hiu.name === "string" ? hiu.name : ""),
    hipName: (typeof hip.name === "string" && hip.name) || (typeof hip.id === "string" ? hip.id : ""),
    hipId: typeof hip.id === "string" ? hip.id : "",
    hiuId: typeof hiu.id === "string" ? hiu.id : "",
    purposeText: typeof purpose.text === "string" ? purpose.text : "",
    hiTypes: Array.isArray(hiType) ? hiType.filter((h): h is string => typeof h === "string") : [],
    periodFrom: typeof dateRange.from === "string" ? dateRange.from : "",
    periodTo: typeof dateRange.to === "string" ? dateRange.to : "",
    dataEraseAt: typeof permission.dataEraseAt === "string" ? permission.dataEraseAt : "",
    careContexts,
    consentId: typeof detail.consentId === "string" ? detail.consentId : typeof detail.requestId === "string" ? detail.requestId : "",
  };
}

/** #9's own response: a bare array, not wrapped -- see consent.py's own get_consent_artefacts_by_request() docstring. */
function extractArtefactsByRequest(body: unknown): ConsentArtefactDetail[] | null {
  if (!Array.isArray(body)) return null;
  const out: ConsentArtefactDetail[] = [];
  for (const item of body) {
    const parsed = extractArtefactItem(item);
    if (parsed !== null) out.push(parsed);
  }
  return out;
}

/** #11's own response: wrapped under consentArtefacts[]. */
function extractAllArtefacts(body: unknown): ConsentArtefactDetail[] | null {
  if (body === null || typeof body !== "object" || !("consentArtefacts" in body)) return null;
  const artefacts = (body as { consentArtefacts: unknown }).consentArtefacts;
  if (!Array.isArray(artefacts)) return null;
  const out: ConsentArtefactDetail[] = [];
  for (const item of artefacts) {
    const parsed = extractArtefactItem(item);
    if (parsed !== null) out.push(parsed);
  }
  return out;
}

interface RequesterGroup {
  key: string;
  label: string;
  artefacts: ConsentArtefactDetail[];
}

/** Groups the Approved tab's flat artefact list by requester -- same pattern as HomeScreen.tsx's own groupByHip(), for the same reason: one requester can appear via several HIPs. Display-only grouping, not a data/fetch change. */
function groupByRequester(artefacts: ConsentArtefactDetail[]): RequesterGroup[] {
  const groups = new Map<string, RequesterGroup>();
  for (const artefact of artefacts) {
    const key = artefact.requesterName || "unknown-requester";
    const label = artefact.requesterName || "Unknown requester";
    const existing = groups.get(key);
    if (existing) existing.artefacts.push(artefact);
    else groups.set(key, { key, label, artefacts: [artefact] });
  }
  return Array.from(groups.values());
}

// --- Approve picker: sourced from Linked Records (spec §9), see P8's own ---
// task prompt banner below for the full "why a picker" story.

interface PickerRecord {
  hipId: string;
  hipName: string;
  hiType: string;
  referenceNumber: string;
  display: string;
  /**
   * NOT declared in either the spec's own §9.3.5 documented shape or its
   * backend pydantic model (links.py's LinkedCareContext) -- read
   * defensively here in case a real response carries it anyway (this
   * project's own established pattern: the backend never strips fields
   * the model doesn't declare, so an undocumented field surviving to
   * here would still be visible). If genuinely absent, falls back to
   * whatever an EXISTING granted artefact for the same HIP already
   * carries (fallbackPatientRefByHip below) -- same patient, same HIP,
   * so its own patientReference should be stable across grants. If
   * NEITHER source has it, submitted as "" -- flagged as a real,
   * unresolved gap in this pass's own report, not silently assumed safe.
   */
  patientReference: string;
}

function extractPickerRecords(body: unknown): PickerRecord[] | null {
  if (body === null || typeof body !== "object" || !("patient" in body)) return null;
  const patient = (body as { patient: unknown }).patient;
  if (patient === null || typeof patient !== "object" || !("links" in patient)) return null;
  const links = (patient as { links: unknown }).links;
  if (!Array.isArray(links)) return null;

  const out: PickerRecord[] = [];
  for (const item of links) {
    if (item === null || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const hip = objField(record, "hip");
    const rawCareContexts = record.careContexts;
    const firstNested = Array.isArray(rawCareContexts) ? objField({ v: rawCareContexts[0] }, "v") : {};
    const patientReference =
      (typeof record.patientReference === "string" && record.patientReference) ||
      (typeof firstNested.patientReference === "string" ? firstNested.patientReference : "");
    out.push({
      hipId: typeof hip.id === "string" ? hip.id : "",
      hipName: typeof hip.name === "string" ? hip.name : "",
      hiType: typeof record.hiType === "string" ? record.hiType : "",
      referenceNumber: typeof record.referenceNumber === "string" ? record.referenceNumber : "",
      display: typeof record.display === "string" ? record.display : "",
      patientReference,
    });
  }
  return out;
}

interface PickerHipGroup {
  key: string;
  label: string;
  records: PickerRecord[];
}

function groupPickerByHip(records: PickerRecord[]): PickerHipGroup[] {
  const groups = new Map<string, PickerHipGroup>();
  for (const record of records) {
    const key = record.hipId || record.hipName || "unknown-hip";
    const label = record.hipName || record.hipId || "Unknown HIP";
    const existing = groups.get(key);
    if (existing) existing.records.push(record);
    else groups.set(key, { key, label, records: [record] });
  }
  return Array.from(groups.values());
}

export function ConsentScreen(): JSX.Element {
  const [sessionToken] = useState(() => getSessionToken());
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const [activeTab, setActiveTab] = useState<"requests" | "approved">("requests");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");

  // --- Level 1: requests list ---
  const [requestsResult, setRequestsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const requests = extractConsentRequests(requestsResult?.data?.body ?? null);

  /**
   * BUG FIX, 2026-09-02 (Aayush, directly, following straight on from the
   * Level-2 fix above -- "shouldn't the outside show Granted? As there
   * are some still granted. Isn't it misleading to the patient?"):
   * that Level-2 fix alone wasn't enough -- it made the DRILL-DOWN show
   * the truth, but Level 1's own badge still came straight from #4's own
   * per-request status word, so the LIST ITSELF kept showing "REVOKED"
   * for a doctor who still has an active grant against another facility.
   * Aayush's own explicit preference: if even one covered facility is
   * still GRANTED, the request should read as GRANTED at this level too
   * -- not "split" here (Level 2 already does the honest per-facility
   * split; Level 1 is a summary, and a misleading summary is worse than
   * no summary).
   *
   * Fetches #9 for every NON-"REQUESTED" request in the list (a still-
   * open request can't have artefacts yet, no point) right after the
   * list itself loads, in parallel -- cached here by requestId so
   * openRequest() below can reuse it instead of re-fetching when the
   * patient actually drills in. Yes, this is an extra call per decided
   * request rather than the single #4 call Level 1 used to make alone --
   * accepted deliberately, since accuracy at the list level is what was
   * explicitly asked for, and this sandbox account's own request volume
   * is small enough that the extra calls are not a real problem.
   */
  const [artefactsCacheByRequestId, setArtefactsCacheByRequestId] = useState<Record<string, ApiResult<AbdmPassthrough>>>({});

  const fetchRequests = async (): Promise<void> => {
    const result = await getAllConsentRequests({ xToken: sessionToken });
    setRequestsResult(result);
    setArtefactsCacheByRequestId({});

    const parsed = extractConsentRequests(result.data?.body ?? null);
    if (parsed === null) return;
    const decided = parsed.filter((r) => r.status.toUpperCase() !== "REQUESTED");
    if (decided.length === 0) return;

    const pairs = await Promise.all(
      decided.map(async (r) => [r.requestId, await getConsentArtefactsByRequest({ xToken: sessionToken, consentRequestId: r.requestId })] as const),
    );
    setArtefactsCacheByRequestId(Object.fromEntries(pairs));
  };

  /** GRANTED if ANY cached artefact for this request is GRANTED, else the request's own #4-reported status (nothing cached yet, or none of its facilities are granted). */
  const effectiveStatus = (request: ConsentRequestSummary): string => {
    const cached = artefactsCacheByRequestId[request.requestId];
    if (cached === undefined) return request.status;
    const artefacts = extractArtefactsByRequest(cached.data?.body ?? null);
    if (artefacts === null || artefacts.length === 0) return request.status;
    return artefacts.some((a) => a.status.toUpperCase() === "GRANTED") ? "GRANTED" : request.status;
  };

  const filteredRequests = requests?.filter((r) => statusFilter === "ALL" || effectiveStatus(r).toUpperCase() === statusFilter) ?? null;

  // --- Level 2: one request's own artefacts (granted) or pending detail ---
  const [selectedRequest, setSelectedRequest] = useState<ConsentRequestSummary | null>(null);
  const [requestArtefactsResult, setRequestArtefactsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [pendingDetailResult, setPendingDetailResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [denyReason, setDenyReason] = useState("");
  const [decisionResult, setDecisionResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const requestArtefacts = extractArtefactsByRequest(requestArtefactsResult?.data?.body ?? null);
  const pendingDetail = extractRequestDetail(pendingDetailResult?.data?.body ?? null);
  const requestStatus = selectedRequest?.status.toUpperCase() ?? "";
  /**
   * BUG FIX, 2026-09-02 (Aayush, directly: a doctor's request covering
   * multiple HIPs, with only ONE of them revoked, showed as flatly
   * "revoked" for the whole doctor -- "the consent is available still,
   * I'm not saying its gone... it's more a display bug"): the old code
   * decided artefacts-vs-detail purely from the REQUEST's own #4-reported
   * `status` word (only fetching #9's real per-HIP breakdown when that
   * word was literally "GRANTED") -- so a request ABDM now reports as
   * "REVOKED" at the request level (apparently its own aggregate once
   * ANY one covered HIP is revoked, not "every HIP is gone") fell into
   * the flat #5 branch instead, which has no per-HIP data at all and
   * hid the still-active HIP(s) entirely. Fixed by trying #9 FIRST for
   * any non-pending request regardless of what word #4 reports, and
   * only falling back to #5's flat view when #9 genuinely comes back
   * empty (a request that was denied/expired without ever producing any
   * artefact) -- see openRequest() below. `hasArtefacts` (whether that
   * fetch actually found something), not the ambiguous request-level
   * status word, is what now decides which branch renders.
   */
  const hasArtefacts = requestArtefacts !== null && requestArtefacts.length > 0;
  /** The only status ABDM lets a patient act on -- everything else (DENIED/EXPIRED/REVOKED) is a terminal, read-only state. */
  const isActionableRequest = requestStatus === "REQUESTED";

  /**
   * P8 -- Approve picker. Source of HIP/care-context choices: Linked
   * Records (spec §9), fetched independently here rather than lifted
   * from HomeScreen.tsx's own state (a second fetch of the same endpoint
   * from a different screen -- this app already does this elsewhere, see
   * this screen's own banner update below). existingArtefactsResult is a
   * SEPARATE fetch of #11 (GRANTED only) used purely as a fallback source
   * for patientReference, which Linked Records' own documented shape
   * never declares -- see PickerRecord's own docstring above.
   */
  const [linkedRecordsResult, setLinkedRecordsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [existingArtefactsResult, setExistingArtefactsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [selectedCareContexts, setSelectedCareContexts] = useState<Record<string, Set<string>>>({});

  const pickerRecords = extractPickerRecords(linkedRecordsResult?.data?.body ?? null);
  const fallbackPatientRefByHip = new Map<string, string>();
  for (const artefact of extractAllArtefacts(existingArtefactsResult?.data?.body ?? null) ?? []) {
    if (artefact.hipId === "" || fallbackPatientRefByHip.has(artefact.hipId)) continue;
    const withRef = artefact.careContexts.find((cc) => cc.patientReference !== "");
    if (withRef !== undefined) fallbackPatientRefByHip.set(artefact.hipId, withRef.patientReference);
  }
  const wantedHiTypes = pendingDetail?.hiTypes ?? [];
  const pickerRecordsFiltered =
    pickerRecords === null
      ? null
      : wantedHiTypes.length === 0
        ? pickerRecords
        : pickerRecords.filter((r) => wantedHiTypes.some((h) => h.toLowerCase() === r.hiType.toLowerCase()));
  /** Only true once filtering by the request's own hiTypes actually dropped something -- distinguishes "unfiltered, nothing linked at all" from "filtered, and everything got excluded" for the picker's own empty-state copy. */
  const pickerFilteredToNothing =
    pickerRecordsFiltered !== null && pickerRecordsFiltered.length === 0 && pickerRecords !== null && pickerRecords.length > 0;

  const toggleCareContext = (hipId: string, referenceNumber: string): void => {
    setSelectedCareContexts((prev) => {
      const next = { ...prev };
      const current = new Set(next[hipId] ?? []);
      if (current.has(referenceNumber)) current.delete(referenceNumber);
      else current.add(referenceNumber);
      next[hipId] = current;
      return next;
    });
  };

  const toggleHipAll = (hipId: string, referenceNumbers: string[]): void => {
    setSelectedCareContexts((prev) => {
      const current = prev[hipId] ?? new Set<string>();
      const allSelected = referenceNumbers.every((r) => current.has(r));
      return { ...prev, [hipId]: new Set(allSelected ? [] : referenceNumbers) };
    });
  };

  const openRequest = (request: ConsentRequestSummary): void => {
    void run(async () => {
      setSelectedRequest(request);
      setRequestArtefactsResult(null);
      setPendingDetailResult(null);
      setDecisionResult(null);
      setLinkedRecordsResult(null);
      setExistingArtefactsResult(null);
      setSelectedCareContexts({});

      if (request.status.toUpperCase() === "REQUESTED") {
        // Still open, never granted -- can't have artefacts yet, no point calling #9 at all.
        // Also loads the Approve picker's own two data sources here (P8) --
        // only worth fetching for a request that can actually still be
        // acted on, not for a terminal one.
        const [detailResult, linkedResult, existingResult] = await Promise.all([
          getConsentRequestDetails({ xToken: sessionToken, consentRequestId: request.requestId }),
          getAllLinkedRecords({ xToken: sessionToken }),
          getAllConsentArtefacts({ xToken: sessionToken, status: "GRANTED" }),
        ]);
        setPendingDetailResult(detailResult);
        setLinkedRecordsResult(linkedResult);
        setExistingArtefactsResult(existingResult);
        return;
      }

      // Reuse what fetchRequests() already fetched for the Level-1 badge above -- same call, no need to hit #9 twice.
      const cached = artefactsCacheByRequestId[request.requestId];
      const artefactsResult = cached ?? (await getConsentArtefactsByRequest({ xToken: sessionToken, consentRequestId: request.requestId }));
      setRequestArtefactsResult(artefactsResult);
      const parsedArtefacts = extractArtefactsByRequest(artefactsResult.data?.body ?? null);
      if (parsedArtefacts === null || parsedArtefacts.length === 0) {
        // No per-HIP artefacts exist for this request at all (e.g. denied
        // or expired without ever being granted) -- fall back to the flat,
        // request-level view, the only one that has anything to show.
        setPendingDetailResult(await getConsentRequestDetails({ xToken: sessionToken, consentRequestId: request.requestId }));
      }
    });
  };

  // --- Level 3: a single artefact's full detail (from either tab) ---
  const [selectedArtefact, setSelectedArtefact] = useState<ConsentArtefactDetail | null>(null);
  const [revokeResult, setRevokeResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const revoke = (consentId: string, onDone: () => void): void => {
    void run(async () => {
      const result = await revokeConsents({ xToken: sessionToken, consentIds: [consentId] });
      setRevokeResult(result);
      if (result.data?.ok === true) onDone();
    });
  };

  // --- "Approved" tab: #11, grouped by requester ---
  // BUG FIX, 2026-09-02 (Aayush, directly: "Even though i revoking consent
  // and geta success I still keep seeing the Requests in my approved
  // tab"): the revoke call itself was working correctly the whole time --
  // fetchApproved() already re-ran after every successful revoke. The
  // actual bug was this fetch's own `status` param: left unset, which
  // means the BACKEND's own default takes over (GetAllConsentArtefactsBody.status
  // = "ALL", see schemas.py) -- so the refreshed list kept legitimately
  // including the just-revoked artefact (now genuinely present with
  // status "REVOKED"), and nothing here ever filtered it back out before
  // rendering. Two-layer fix: request only GRANTED ones explicitly (less
  // data pulled, matches this tab's own name/intent), AND filter
  // defensively client-side too, in case a future response ever includes
  // something ABDM's own status filter didn't catch -- same "don't trust
  // a single mechanism" convention as every other parser in this file.
  const [approvedResult, setApprovedResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const approvedArtefacts = extractAllArtefacts(approvedResult?.data?.body ?? null)?.filter(
    (artefact) => artefact.status.toUpperCase() === "GRANTED",
  ) ?? null;
  const fetchApproved = async (): Promise<void> => {
    setApprovedResult(await getAllConsentArtefacts({ xToken: sessionToken, status: "GRANTED" }));
  };

  // --- Auto-Approve (unchanged from the prior version -- secondary section) ---
  const [showAutoApprove, setShowAutoApprove] = useState(false);
  const [hiuId, setHiuId] = useState("");
  const [selectedHiTypes, setSelectedHiTypes] = useState<string[]>([]);
  const [purposeText, setPurposeText] = useState("Care Management");
  const [purposeCode, setPurposeCode] = useState("CAREMGT");
  const [purposeRefUri, setPurposeRefUri] = useState("www.abdm.gov.in");
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [applyToAllHips, setApplyToAllHips] = useState(true);
  const [autoApproveResult, setAutoApproveResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [autoApproveConsentId, setAutoApproveConsentId] = useState("");
  const [autoApproveStateResult, setAutoApproveStateResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  /** P13 -- discover-self-view-consents' own last result (see data_flow.py's own discover_self_view_consents() docstring). */
  const [discoverResult, setDiscoverResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  /** P8 item 3 -- last consentId seen via a Level-3 artefact view, prefilled into Auto-Approve's own manual field below when opened, since a bare unlabeled textbox is a bad UX for a real, standing spec gap (§6.13's response never documents how a caller learns a consentId at all). */
  const [lastViewedConsentId, setLastViewedConsentId] = useState("");

  const toggleHiType = (hiType: string): void => {
    setSelectedHiTypes((prev) => (prev.includes(hiType) ? prev.filter((h) => h !== hiType) : [...prev, hiType]));
  };

  if (sessionToken === "") {
    return (
      <section className="panel">
        <PageHeader icon={ShieldCheck} title="Consent Manager" />
        <p className="muted">Log in first to manage consent.</p>
      </section>
    );
  }

  // --- Level 3 render: one artefact's full detail, reused by both tabs ---
  if (selectedArtefact !== null) {
    const artefact = selectedArtefact;
    const badge = statusBadge(artefact.status);
    return (
      <section className="panel">
        <PageHeader icon={ShieldCheck} title="Consent Manager" />
        <Button size="sm" icon={ArrowLeft} onClick={() => setSelectedArtefact(null)}>Back</Button>

        <Card padding="md" className="ui-card--flush">
          <CardBody>
            <div className="ui-card__header">
              {artefact.requesterName !== "" && <CardTitle icon={User}>{artefact.requesterName}</CardTitle>}
              <Badge tone={badge.tone} icon={badge.icon}>{badge.label}</Badge>
            </div>

            <p className="ui-card__label"><CalendarClock size={13} aria-hidden="true" /> Information request duration</p>
            <p className="result">
              From {formatDate(artefact.periodFrom) || "—"} To {formatDate(artefact.periodTo) || "—"}
            </p>

            <p className="ui-card__label"><FileText size={13} aria-hidden="true" /> Information request type</p>
            {artefact.hiTypes.length === 0 ? (
              <p className="result">—</p>
            ) : (
              <ul>
                {artefact.hiTypes.map((hiType) => (
                  <li key={hiType}>{hiType}</li>
                ))}
              </ul>
            )}

            <p className="ui-card__label"><Hourglass size={13} aria-hidden="true" /> Consent valid upto</p>
            <p className="result">{formatDate(artefact.dataEraseAt) || "—"}</p>

            <p className="ui-card__label"><ShieldCheck size={13} aria-hidden="true" /> You have given access to</p>
            <div className="field field--block">
              <label className="row">
                <input type="checkbox" checked disabled />
                <strong>{artefact.hipName || "Unknown HIP"}</strong>
              </label>
              <ul>
                {artefact.careContexts.map((cc, index) => (
                  <li key={`${cc.careContextReference}-${index}`}>
                    <label className="row">
                      <input type="checkbox" checked disabled />
                      {cc.careContextReference || cc.patientReference || "—"}
                    </label>
                  </li>
                ))}
              </ul>
              {artefact.careContexts.length === 0 && <p className="muted">No care contexts listed.</p>}
            </div>
          </CardBody>
          <CardFooter>
            <Button
              variant="danger"
              icon={Ban}
              disabled={busy || artefact.consentId === ""}
              onClick={() =>
                revoke(artefact.consentId, () => {
                  setSelectedArtefact(null);
                  if (activeTab === "requests" && selectedRequest !== null) openRequest(selectedRequest);
                  else if (activeTab === "requests") void run(fetchRequests);
                  else void run(fetchApproved);
                })
              }
            >
              Revoke consent
            </Button>
          </CardFooter>
        </Card>
        <p className="muted">
          Consent ID used: <code>{artefact.consentId || "—"}</code>
        </p>
        <RawBody label="revoke" result={revokeResult} />
      </section>
    );
  }

  return (
    <section className="panel">
      <PageHeader
        icon={ShieldCheck}
        title="Consent Manager"
        description="Control who gets to read the data behind your linked records. This screen does not show any actual health-record content — only who has, or is asking for, permission to read it."
      />

      <SegmentedControl
        options={[
          { value: "requests" as const, label: "Requests" },
          { value: "approved" as const, label: "Approved" },
        ]}
        value={activeTab}
        onChange={(next) => {
          setSelectedRequest(null);
          if (next === "requests") { setActiveTab("requests"); void run(fetchRequests); }
          else { setActiveTab("approved"); void run(fetchApproved); }
        }}
      />

      {activeTab === "requests" && selectedRequest === null && (
        <>
          <div className="ui-status-filter-bar">
            <div className="ui-status-filter">
              {STATUS_FILTERS.map((filter) => (
                <button
                  key={filter}
                  type="button"
                  className={`ui-status-filter__option${statusFilter === filter ? " ui-status-filter__option--active" : ""}`}
                  onClick={() => setStatusFilter(filter)}
                >
                  {statusFilterLabel(filter)}
                </button>
              ))}
            </div>
            <Button size="sm" icon={RefreshCw} disabled={busy} onClick={() => void run(fetchRequests)} className="ui-status-filter__refresh">
              Refresh
            </Button>
          </div>
          <RawBody label="requests/get-all" result={requestsResult} />

          {filteredRequests !== null && filteredRequests.length === 0 && (
            <EmptyState icon={Inbox} message="No consent requests." />
          )}

          {filteredRequests !== null && filteredRequests.length > 0 && (
            <CardGrid minWidth={280}>
              {filteredRequests.map((request) => {
                const badge = statusBadge(effectiveStatus(request));
                return (
                  <Card key={request.requestId} padding="sm">
                    <div className="ui-card__header">
                      <CardTitle icon={User}>{request.requesterName || "Unknown requester"}</CardTitle>
                      <Badge tone={badge.tone} icon={badge.icon}>{badge.label}</Badge>
                    </div>
                    <CardBody>
                      <p className="ui-card__label">Purpose of request</p>
                      <p className="ui-card__value">{request.purposeText || "—"}</p>
                      <p className="ui-card__label">Information request duration</p>
                      <p className="ui-card__value">
                        From {formatDate(request.periodFrom) || "—"} To {formatDate(request.periodTo) || "—"}
                      </p>
                    </CardBody>
                    <CardFooter>
                      <Button size="sm" icon={Eye} disabled={busy} onClick={() => openRequest(request)}>
                        View details
                      </Button>
                    </CardFooter>
                  </Card>
                );
              })}
            </CardGrid>
          )}

          {requestsResult?.data?.ok === true && requests === null && (
            <p className="muted">The response didn&apos;t match the expected shape — check the raw response above.</p>
          )}
        </>
      )}

      {activeTab === "requests" && selectedRequest !== null && (
        <>
          <Button size="sm" icon={ArrowLeft} onClick={() => setSelectedRequest(null)}>Back to requests</Button>
          <PageHeader
            icon={User}
            title={selectedRequest.requesterName || "Unknown requester"}
            actions={(() => {
              const badge = statusBadge(selectedRequest.status);
              return <Badge tone={badge.tone} icon={badge.icon}>{badge.label}</Badge>;
            })()}
          />

          {hasArtefacts ? (
            <>
              <p className="muted">
                {requestArtefacts !== null && requestArtefacts.length > 1
                  ? "This request covers more than one facility — each one's own status is shown below, since revoking one doesn't affect the others."
                  : "This request's own facility, with its current status."}
              </p>
              <RawBody label="artefacts/get-by-request" result={requestArtefactsResult} />

              {requestArtefacts !== null && requestArtefacts.length > 0 && (
                <CardGrid minWidth={260}>
                  {requestArtefacts.map((artefact, index) => {
                    const artefactBadge = statusBadge(artefact.status);
                    const artefactGranted = artefact.status.toUpperCase() === "GRANTED";
                    return (
                      <Card key={`${artefact.consentId}-${index}`} padding="sm">
                        <div className="ui-card__header">
                          <CardTitle icon={Building2}>{artefact.hipName || "Unknown HIP"}</CardTitle>
                          <Badge tone={artefactBadge.tone} icon={artefactBadge.icon}>{artefactBadge.label}</Badge>
                        </div>
                        <CardBody>
                          <p className="ui-card__label">Purpose of request</p>
                          <p className="ui-card__value">{artefact.purposeText || "—"}</p>
                        </CardBody>
                        <CardFooter>
                          <Button
                            size="sm"
                            icon={Eye}
                            onClick={() => {
                              setSelectedArtefact({ ...artefact, requesterName: selectedRequest.requesterName });
                              setLastViewedConsentId(artefact.consentId);
                            }}
                          >
                            View details
                          </Button>
                          {artefactGranted && (
                            <Button
                              variant="danger"
                              size="sm"
                              icon={Ban}
                              disabled={busy || artefact.consentId === ""}
                              onClick={() =>
                                revoke(artefact.consentId, () => {
                                  if (selectedRequest !== null) void openRequest(selectedRequest);
                                })
                              }
                            >
                              Revoke
                            </Button>
                          )}
                        </CardFooter>
                      </Card>
                    );
                  })}
                </CardGrid>
              )}

              {requestArtefactsResult?.data?.ok === true && requestArtefacts === null && (
                <p className="muted">The response didn&apos;t match the expected shape (expected a bare array) — check the raw response above.</p>
              )}
            </>
          ) : (
            <>
              <p className="muted">
                {isActionableRequest
                  ? "This request is still pending — review and decide below."
                  : "This request has already been decided — no further action is possible."}
              </p>
              <RawBody label="requests/get-one" result={pendingDetailResult} />

              {pendingDetail !== null && (
                <Card padding="md" className="ui-card--flush">
                  <CardBody>
                    <p className="ui-card__label">Purpose of request</p>
                    <p className="ui-card__value">{pendingDetail.purposeText || "—"}</p>
                    <p className="ui-card__label">Information request type</p>
                    {pendingDetail.hiTypes.length === 0 ? (
                      <p className="ui-card__value">—</p>
                    ) : (
                      <ul>
                        {pendingDetail.hiTypes.map((hiType) => (
                          <li key={hiType}>{hiType}</li>
                        ))}
                      </ul>
                    )}
                    <p className="ui-card__label">Information request duration</p>
                    <p className="ui-card__value">
                      From {formatDate(pendingDetail.periodFrom) || "—"} To {formatDate(pendingDetail.periodTo) || "—"}
                    </p>
                    <p className="ui-card__label">Consent valid upto</p>
                    <p className="ui-card__value">{formatDate(pendingDetail.dataEraseAt) || "—"}</p>
                  </CardBody>
                </Card>
              )}

              {pendingDetailResult?.data?.ok === true && pendingDetail === null && (
                <p className="muted">The response didn&apos;t match the expected shape — check the raw response above.</p>
              )}

              {isActionableRequest && (
                <>
                  {/*
                    P8 -- Approve picker. Approving submits back the SPECIFIC
                    hip/careContexts being granted (consent.py's own "full-
                    acceptance-only" design note is about hiTypes/permission,
                    NOT about skipping HIP selection -- #5's own confirmed
                    live shape never carries a hip/careContexts to accept
                    as-is, see this screen's own banner). hiTypes/permission
                    are still submitted UNCHANGED from the request's own
                    values, per that same scope decision -- only WHICH HIP(s)
                    and care context(s) is a real choice here.
                  */}
                  <p className="ui-card__label">Approve — choose which facility/record(s) to grant access to</p>

                  {wantedHiTypes.length > 0 && (
                    <p className="muted">
                      This request wants: <strong>{wantedHiTypes.join(", ")}</strong>
                      {pickerRecords !== null && pickerRecords.length > 0 && " — the list below is already filtered to matching records."}
                    </p>
                  )}

                  {linkedRecordsResult === null && <p className="muted">Loading your linked records…</p>}

                  {linkedRecordsResult !== null && linkedRecordsResult.data?.ok !== true && (
                    <Callout tone="warning" icon={Ban}>
                      Couldn&apos;t load your linked records, so there&apos;s nothing to build an Approve
                      submission from right now — check the Console for details, or use Deny below.
                    </Callout>
                  )}

                  {pickerRecords !== null && pickerRecords.length === 0 && (
                    <Callout icon={Inbox}>
                      No linked facilities to grant access from yet — link a record first (HIP-Initiated
                      Linking), then come back to approve this request.
                    </Callout>
                  )}

                  {pickerFilteredToNothing && (
                    <Callout tone="warning" icon={Ban}>
                      None of your linked records match this request&apos;s own wanted information
                      type(s) ({wantedHiTypes.join(", ")}) — nothing to select. Use Deny below.
                    </Callout>
                  )}

                  {pickerRecordsFiltered !== null && pickerRecordsFiltered.length > 0 && (
                    <>
                      <CardGrid minWidth={280}>
                        {groupPickerByHip(pickerRecordsFiltered).map((group) => {
                          const refs = group.records.map((r) => r.referenceNumber);
                          const selected = selectedCareContexts[group.key] ?? new Set<string>();
                          const allSelected = refs.length > 0 && refs.every((r) => selected.has(r));
                          return (
                            <Card key={group.key} padding="sm">
                              <CardTitle icon={Building2}>{group.label}</CardTitle>
                              <CardBody>
                                <label className="row">
                                  <input type="checkbox" checked={allSelected} onChange={() => toggleHipAll(group.key, refs)} />
                                  <strong>Select all at this facility</strong>
                                </label>
                                <ul>
                                  {group.records.map((record, index) => (
                                    <li key={`${record.referenceNumber}-${index}`}>
                                      <label className="row">
                                        <input
                                          type="checkbox"
                                          checked={selected.has(record.referenceNumber)}
                                          onChange={() => toggleCareContext(group.key, record.referenceNumber)}
                                        />
                                        {record.display || record.hiType || record.referenceNumber || "—"}
                                      </label>
                                    </li>
                                  ))}
                                </ul>
                              </CardBody>
                            </Card>
                          );
                        })}
                      </CardGrid>

                      <Button
                        variant="primary"
                        size="sm"
                        icon={Check}
                        disabled={busy || Object.values(selectedCareContexts).every((s) => s.size === 0)}
                        onClick={() =>
                          void run(async () => {
                            const consents: ConsentGrant[] = [];
                            for (const group of groupPickerByHip(pickerRecordsFiltered)) {
                              const selected = selectedCareContexts[group.key] ?? new Set<string>();
                              if (selected.size === 0) continue;
                              const chosenRecords = group.records.filter((r) => selected.has(r.referenceNumber));
                              consents.push({
                                hiTypes: wantedHiTypes,
                                hip: { id: group.key },
                                careContexts: chosenRecords.map((r) => ({
                                  patientReference: r.patientReference || fallbackPatientRefByHip.get(group.key) || "",
                                  careContextReference: r.referenceNumber,
                                })),
                                permission: {
                                  // pendingDetail (#5's own freshly-fetched detail), not the
                                  // Level-1 list item -- the authoritative per-request source,
                                  // see this screen's own banner. Falls back to the list item
                                  // only if #5 itself somehow never parsed.
                                  dateRange: {
                                    from: pendingDetail?.periodFrom || selectedRequest.periodFrom,
                                    to: pendingDetail?.periodTo || selectedRequest.periodTo,
                                  },
                                  frequency: { unit: "HOUR", value: 0, repeats: 0 },
                                  accessMode: "VIEW",
                                  dataEraseAt: pendingDetail?.dataEraseAt || selectedRequest.dataEraseAt,
                                },
                              });
                            }
                            const result = await approveConsentRequest({ xToken: sessionToken, consentRequestId: selectedRequest.requestId, consents });
                            setDecisionResult(result);
                            if (result.data?.ok === true) {
                              setSelectedRequest(null);
                              void run(fetchRequests);
                            }
                          })
                        }
                      >
                        Approve selected
                      </Button>
                    </>
                  )}

                  <p className="ui-card__label">Or deny this request</p>
                  <label className="row">
                    <span>Deny reason</span>
                    <input type="text" value={denyReason} onChange={(event) => setDenyReason(event.target.value)} />
                  </label>
                  <Button
                    variant="danger"
                    size="sm"
                    icon={X}
                    disabled={busy || denyReason === ""}
                    onClick={() =>
                      void run(async () => {
                        const result = await denyConsentRequest({ xToken: sessionToken, consentRequestId: selectedRequest.requestId, reason: denyReason });
                        setDecisionResult(result);
                        if (result.data?.ok === true) {
                          setSelectedRequest(null);
                          setDenyReason("");
                          void run(fetchRequests);
                        }
                      })
                    }
                  >
                    Deny
                  </Button>
                  <RawBody label="requests/approve-or-deny" result={decisionResult} />
                </>
              )}
            </>
          )}
        </>
      )}

      {activeTab === "approved" && (
        <>
          <Button size="sm" icon={RefreshCw} disabled={busy} onClick={() => void run(fetchApproved)}>
            Refresh
          </Button>
          <RawBody label="artefacts/get-all" result={approvedResult} />

          {approvedArtefacts !== null && approvedArtefacts.length === 0 && (
            <EmptyState icon={Inbox} message="No active consents." />
          )}

          {approvedArtefacts !== null && approvedArtefacts.length > 0 && (
            <div className="field field--block">
              {groupByRequester(approvedArtefacts).map((group) => (
                <div key={group.key}>
                  <h3><User size={15} aria-hidden="true" /> {group.label}</h3>
                  <CardGrid minWidth={260}>
                    {group.artefacts.map((artefact, index) => (
                      <Card key={`${artefact.consentId}-${index}`} padding="sm">
                        <CardTitle icon={Building2}>{artefact.hipName || "Unknown HIP"}</CardTitle>
                        <CardBody>
                          <p className="ui-card__label">Purpose of request</p>
                          <p className="ui-card__value">{artefact.purposeText || "—"}</p>
                        </CardBody>
                        <CardFooter>
                          <Button
                            size="sm"
                            icon={Eye}
                            onClick={() => {
                              setSelectedArtefact(artefact);
                              setLastViewedConsentId(artefact.consentId);
                            }}
                          >
                            View details
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            icon={Ban}
                            disabled={busy || artefact.consentId === ""}
                            onClick={() => revoke(artefact.consentId, () => void run(fetchApproved))}
                          >
                            Revoke
                          </Button>
                        </CardFooter>
                      </Card>
                    ))}
                  </CardGrid>
                </div>
              ))}
            </div>
          )}

          {approvedResult?.data?.ok === true && approvedArtefacts === null && (
            <p className="muted">The response didn&apos;t match the expected shape — check the raw response above.</p>
          )}
        </>
      )}

      {/* --- Auto-Approve (secondary, policy not per-request) ------------ */}
      <fieldset className="step" disabled={busy}>
        <legend><RefreshCw size={15} aria-hidden="true" /> Auto-Approve (policy, not per-request)</legend>
        {!showAutoApprove ? (
          <Button
            size="sm"
            onClick={() => {
              setShowAutoApprove(true);
              if (autoApproveConsentId === "" && lastViewedConsentId !== "") setAutoApproveConsentId(lastViewedConsentId);
            }}
          >
            Auto-Approve settings
          </Button>
        ) : (
          <>
            <label className="row">
              <span>HIU ID</span>
              <input type="text" value={hiuId} onChange={(event) => setHiuId(event.target.value)} />
            </label>
            <div className="row">
              <span>HI Types</span>
              {HI_TYPES.map((hiType) => (
                <button
                  key={hiType}
                  type="button"
                  className={`chip ${selectedHiTypes.includes(hiType) ? "chip--on" : ""}`}
                  onClick={() => toggleHiType(hiType)}
                >
                  {hiType}
                </button>
              ))}
            </div>
            <label className="row">
              <span>Purpose text</span>
              <input type="text" value={purposeText} onChange={(event) => setPurposeText(event.target.value)} />
            </label>
            <label className="row">
              <span>Purpose code</span>
              <input type="text" value={purposeCode} onChange={(event) => setPurposeCode(event.target.value)} />
            </label>
            <label className="row">
              <span>Purpose ref URI</span>
              <input type="text" value={purposeRefUri} onChange={(event) => setPurposeRefUri(event.target.value)} />
            </label>
            <label className="row">
              <span>Period from</span>
              <input type="text" value={periodFrom} placeholder="2026-01-01T00:00:00.000Z" onChange={(event) => setPeriodFrom(event.target.value)} />
            </label>
            <label className="row">
              <span>Period to</span>
              <input type="text" value={periodTo} placeholder="2026-12-31T00:00:00.000Z" onChange={(event) => setPeriodTo(event.target.value)} />
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={applyToAllHips} onChange={(event) => setApplyToAllHips(event.target.checked)} />
              Applicable for all HIPs
            </label>
            <Button
              size="sm"
              icon={Send}
              disabled={busy || hiuId === "" || selectedHiTypes.length === 0 || periodFrom === "" || periodTo === ""}
              onClick={() =>
                void run(async () => {
                  setAutoApproveResult(
                    await autoApprove({
                      xToken: sessionToken,
                      hiuId,
                      hiTypes: selectedHiTypes,
                      purposeText,
                      purposeCode,
                      purposeRefUri,
                      periodFrom,
                      periodTo,
                      isApplicableForAllHIPs: applyToAllHips,
                    }),
                  );
                })
              }
            >
              Set Auto-Approve Policy
            </Button>
            <RawBody label="auto-approve" result={autoApproveResult} />

            <p className="muted">
              Enable/disable act on one specific consent artefact&apos;s own auto-approve state, not
              on the policy above — ABDM&apos;s own spec documents §6.13&apos;s create-policy response
              as 202 Accepted with no body at all, so there is no obvious id to read it from (check the
              raw response above after setting a policy — if it turns out to carry an id ABDM just
              never documented, use that). Otherwise, use the <strong>consentId of an already-GRANTED
              consent</strong> instead — visible in the &quot;Approved&quot; tab, or on any
              artefact&apos;s own Level-3 detail view (opening one prefills this field below
              automatically).
            </p>
            <label className="row">
              <span>Consent ID</span>
              <input type="text" value={autoApproveConsentId} onChange={(event) => setAutoApproveConsentId(event.target.value)} />
            </label>
            <Button
              size="sm"
              icon={X}
              disabled={busy || autoApproveConsentId === ""}
              onClick={() => void run(async () => setAutoApproveStateResult(await disableAutoApprove({ xToken: sessionToken, consentId: autoApproveConsentId })))}
            >
              Disable
            </Button>
            <Button
              size="sm"
              icon={Check}
              disabled={busy || autoApproveConsentId === ""}
              onClick={() => void run(async () => setAutoApproveStateResult(await enableAutoApprove({ xToken: sessionToken, consentId: autoApproveConsentId })))}
            >
              Enable
            </Button>
            <RawBody label="auto-approve/enable-or-disable" result={autoApproveStateResult} />
          </>
        )}
      </fieldset>

      {/* --- Discover Self-View Grants (P13) ------------------------------ */}
      <fieldset className="step" disabled={busy}>
        <legend><RefreshCw size={15} aria-hidden="true" /> Discover Self-View Grants</legend>
        <p className="muted">
          ABDM appears to grant self-view (PATRQT) access on its own, independent of the Auto-Approve
          policy above — confirmed live under hiu.id <code>&quot;sbx_001&quot;</code>, requester{" "}
          <code>&quot;SELF&quot;</code>. This checks for any such grants and registers each new one
          locally so &quot;Pull Records&quot; can actually use it. Safe to run repeatedly — already-known
          grants are skipped.
        </p>
        <Button
          size="sm"
          icon={RefreshCw}
          onClick={() => void run(async () => setDiscoverResult(await discoverSelfViewConsents({ xToken: sessionToken })))}
        >
          Discover Self-View Grants
        </Button>
        <RawBody label="discover-self-view-consents" result={discoverResult} />
      </fieldset>
    </section>
  );
}
