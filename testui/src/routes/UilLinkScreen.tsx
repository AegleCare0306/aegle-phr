/**
 * P15 -- User-Initiated Linking (spec §10.3.1-§10.3.12), "Find my records"
 * flow. Aayush's own words: "the first thing I want to implement is being
 * able to see all the linked data to my account" -- everything else in
 * this project got built first, in the order he chose; this is the one he
 * asked for explicitly, last.
 *
 * ONE CONTINUOUS SCREEN, not four separate routes -- per the standing
 * real-app-navigation requirement (P3, reaffirmed by P15): search a
 * provider -> discover -> review found care contexts -> enter the OTP ->
 * confirmation, entirely as phase transitions within this one component.
 * Entry point is ProviderDirectoryScreen.tsx's own "Link this facility"
 * button (per result), which navigates here with the chosen HIP's id/name.
 *
 * POLLING, NOT PUSH: none of the three outbound calls below (discover/
 * link-init/link-confirm) return anything useful synchronously -- all
 * three are bare 202 Accepted, the real answer arrives later as an inbound
 * ABDM callback this app's own backend receives (aegle_phr/callbacks/
 * uil_services.py) and stores keyed by requestId. pollForResult() below is
 * the one polling loop, reused for all three stages -- same shape as
 * HomeScreen.tsx's own pollStatus() (bounded attempts, a visible timeout
 * state with a "Check again" retry, never an infinite spinner), and its
 * WAITING callout matches HomeScreen's own SelfViewWaitingCallout look,
 * per the task spec's explicit instruction to reuse that pattern rather
 * than invent a new one.
 *
 * WHY EXPLICIT GO-AHEAD BEFORE LINK-INIT SPECIFICALLY: that call is the
 * one that makes the HIP send a REAL OTP to the patient's real registered
 * mobile -- same live-testing caution as every other OTP-sending call in
 * this project (AadhaarRegisterScreen, every OtpLoginScreen usage, etc.).
 * Discover itself is a plain lookup (no OTP, no side effect a retry could
 * hurt) so it fires as soon as the patient taps "Find my records" on the
 * intro screen -- that tap IS its own go-ahead, a second confirmation
 * underneath it would just be friction.
 *
 * NO <fieldset>/<legend> ANYWHERE IN THIS FILE -- P14 retired that pattern
 * app-wide; every section below is a Card, every list a ListRow, per the
 * task spec's explicit instruction.
 *
 * ON A SUCCESSFUL CONFIRM: navigates to /home and does NOT build a second
 * "linked via UIL" view -- HomeScreen.tsx's own existing
 * getAllLinkedRecords() (spec §9.3.5) call re-fires on that fresh mount
 * and simply shows the newly-linked care context alongside everything
 * else, since linking is pure ABDM-side metadata with no special-casing by
 * how it was linked. A freshly-linked HIP still needs its own self-view
 * consent before its records are actually readable -- HomeScreen's
 * existing P9 auto-provisioning effect already handles that automatically
 * once the HIP shows up in Linked Records; nothing new is needed here for
 * that part (explicitly out of scope for this chunk, spec §6).
 */

import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Building2,
  Check,
  CheckCircle2,
  FileText,
  Link2,
  Loader2,
  RefreshCw,
  Search,
  Send,
} from "lucide-react";

import { uilDiscover, uilLinkConfirm, uilLinkInit, getUilResult } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card, CardBody, CardTitle } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { markRecentLink } from "../recentLink";
import { getSessionAddress, getSessionToken } from "../session";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** ~30s window, matching the task spec's own stated budget -- generous above how long an ABDM callback is expected to take, short enough that a genuine failure doesn't read as a hang. */
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 10;

function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

function objField(body: unknown, key: string): Record<string, unknown> | null {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (value !== null && typeof value === "object") return value as Record<string, unknown>;
  }
  return null;
}

// --- The polled UilLinkRequest row (aegle_phr/phr/uil_repository.py's own _as_dict() shape) ---

interface CareContextMatch {
  referenceNumber: string;
  display: string;
}

interface PatientMatch {
  referenceNumber: string;
  display: string;
  hiType: string;
  count: number;
  careContexts: CareContextMatch[];
}

interface PolledRow {
  requestId: string;
  stage: string;
  status: string;
  detail: unknown;
  linkRefNumber: string | null;
}

function extractPolledRow(body: unknown): PolledRow | null {
  if (body === null || typeof body !== "object") return null;
  const record = body as Record<string, unknown>;
  if (typeof record.requestId !== "string" || typeof record.status !== "string") return null;
  return {
    requestId: record.requestId,
    stage: typeof record.stage === "string" ? record.stage : "",
    status: record.status,
    detail: record.detail ?? null,
    linkRefNumber: typeof record.linkRefNumber === "string" ? record.linkRefNumber : null,
  };
}

/** Reads the on-discover callback's own `error` field, if the row's detail carries one (shared shape across all three callbacks, see uil_services.py). */
function extractCallbackError(detail: unknown): string | null {
  const error = objField(detail, "error");
  if (error === null) return null;
  const message = typeof error.message === "string" ? error.message : "";
  const code = typeof error.code === "string" ? error.code : "";
  return [code, message].filter((v) => v !== "").join(" — ") || "ABDM returned an error with no further detail.";
}

/**
 * ABDM's own error out of an IMMEDIATE response body (not a callback), with
 * the one case a patient will realistically hit written in plain language.
 *
 * ABDM-9999 "Duplicate Discovery request" fires when a discovery for this
 * same patient and facility is still open on ABDM's side -- confirmed live
 * 2026-09-23. It outlives this screen, so the in-flight `busy` guard does
 * NOT prevent it: starting a search, navigating away and coming back is
 * enough to trigger it. Without this the patient sees the generic
 * "check the Console" fallback for something that is neither their mistake
 * nor fixable by pressing the button again straight away.
 */
function describeRequestError(body: unknown): string | null {
  const error = objField(body, "error");
  if (error === null) return null;
  const message = typeof error.message === "string" ? error.message : "";
  const code = typeof error.code === "string" ? error.code : "";
  if (/duplicate discovery/i.test(message)) {
    return "A record search is already running for this facility. Give it a minute and try again — ABDM allows only one search at a time per facility.";
  }
  return [code.trim().replace(/:$/, ""), message].filter((v) => v !== "").join(" — ") || null;
}

function extractPatientMatches(detail: unknown): PatientMatch[] {
  const record = detail !== null && typeof detail === "object" ? (detail as Record<string, unknown>) : {};
  const rawPatients = record.patient;
  if (!Array.isArray(rawPatients)) return [];
  const out: PatientMatch[] = [];
  for (const item of rawPatients) {
    if (item === null || typeof item !== "object") continue;
    const p = item as Record<string, unknown>;
    const rawContexts = p.careContexts;
    const careContexts: CareContextMatch[] = Array.isArray(rawContexts)
      ? rawContexts
          .filter((cc): cc is Record<string, unknown> => cc !== null && typeof cc === "object")
          .map((cc) => ({
            referenceNumber: typeof cc.referenceNumber === "string" ? cc.referenceNumber : "",
            display: typeof cc.display === "string" ? cc.display : "",
          }))
          .filter((cc) => cc.referenceNumber !== "")
      : [];
    out.push({
      referenceNumber: typeof p.referenceNumber === "string" ? p.referenceNumber : "",
      display: typeof p.display === "string" ? p.display : "",
      hiType: typeof p.hiType === "string" ? p.hiType : "",
      count: typeof p.count === "number" ? p.count : careContexts.length,
      careContexts,
    });
  }
  return out;
}

/**
 * ONE SELECTABLE THING: a single record type belonging to a single visit.
 *
 * This is the unit ABDM actually supports. Its on-discover body is grouped
 * by hiType, and link-init echoes that shape back, so the finest selection
 * the protocol allows is a (careContext, hiType) pair -- "the Prescription
 * from the 15 July visit", not "the 15 July visit" as an indivisible lump.
 */
interface EncounterItem {
  hiType: string;
  patientReference: string;
  patientDisplay: string;
}

/** One visit, with every record type the facility holds for it. */
interface EncounterGroup {
  reference: string;
  /** What ABDM sent, e.g. "Essential Hypertension - 2026-07-15". */
  display: string;
  /** The condition, split off the display for a readable heading. */
  title: string;
  /** The trailing ISO date, if the display carries one. */
  date: string;
  items: EncounterItem[];
}

/** A selection key. Must include the hiType -- see selectedItems' own note. */
function itemKey(reference: string, hiType: string): string {
  return `${reference}|${hiType}`;
}

/**
 * INVERTS ABDM's GROUPING, WHICH IS THE WHOLE POINT OF THIS SCREEN'S
 * REDESIGN. on-discover arrives grouped by hiType, so one visit appears
 * once per record type it holds -- a real payload had
 * "Essential Hypertension - 2026-07-15" listed under Invoice, under
 * OPConsultation AND under Prescription. Rendered in ABDM's own order a
 * patient sees the same date three times under three headings with no way
 * to tell they are one visit, which is exactly the complaint.
 *
 * Regrouping by careContextReference gives the view a patient actually
 * holds in their head: one section per visit, the record types inside it.
 */
function groupByEncounter(matches: PatientMatch[]): EncounterGroup[] {
  const byReference = new Map<string, EncounterGroup>();

  for (const match of matches) {
    for (const cc of match.careContexts) {
      if (cc.referenceNumber === "") continue;
      let group = byReference.get(cc.referenceNumber);
      if (group === undefined) {
        const display = cc.display || cc.referenceNumber;
        // "Condition - YYYY-MM-DD" is the shape every real display has
        // carried so far. Split on the LAST separator so a condition with
        // its own hyphen survives, and fall back to the whole string.
        const dateMatch = display.match(/\s*[-–]\s*(\d{4}-\d{2}-\d{2})\s*$/);
        group = {
          reference: cc.referenceNumber,
          display,
          title: dateMatch ? display.slice(0, dateMatch.index).trim() : display,
          date: dateMatch ? dateMatch[1] : "",
          items: [],
        };
        byReference.set(cc.referenceNumber, group);
      }
      if (match.hiType !== "" && !group.items.some((i) => i.hiType === match.hiType)) {
        group.items.push({
          hiType: match.hiType,
          patientReference: match.referenceNumber,
          patientDisplay: match.display,
        });
      }
    }
  }

  const groups = [...byReference.values()];
  for (const group of groups) group.items.sort((a, b) => a.hiType.localeCompare(b.hiType));
  // Newest visit first. A patient looking for "the one from last week"
  // should not have to scan an arbitrary order.
  groups.sort((a, b) => (b.date || "").localeCompare(a.date || "") || a.title.localeCompare(b.title));
  return groups;
}

/**
 * Rebuilds the patient[]/careContexts[] shape link-init expects, from the
 * selected (visit, record type) pairs.
 *
 * Regrouping BACK to ABDM's hiType-first shape is what lets the screen
 * present visits while the wire still carries what the spec documents --
 * one patient entry per hiType, each listing only the visits selected for
 * that type. A type with nothing selected is dropped entirely.
 */
function buildSelectedPatientPayload(matches: PatientMatch[], selected: Set<string>): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  for (const match of matches) {
    const keptContexts = match.careContexts.filter((cc) => selected.has(itemKey(cc.referenceNumber, match.hiType)));
    if (keptContexts.length === 0) continue;
    out.push({
      referenceNumber: match.referenceNumber,
      display: match.display,
      hiType: match.hiType,
      count: keptContexts.length,
      careContexts: keptContexts.map((cc) => ({ referenceNumber: cc.referenceNumber, display: cc.display })),
    });
  }
  return out;
}

type Phase =
  | "intro"
  | "discovering"
  | "discover_timeout"
  | "review"
  | "confirm_link_init"
  | "linking"
  | "link_timeout"
  | "otp"
  | "confirming"
  | "confirm_timeout"
  | "done";

export function UilLinkScreen(): JSX.Element {
  const navigate = useNavigate();
  const { hipId = "" } = useParams<{ hipId: string }>();
  const [searchParams] = useSearchParams();
  const hipName = searchParams.get("name") || hipId;

  const [sessionToken] = useState(() => getSessionToken());
  const [sessionAddress] = useState(() => getSessionAddress());

  const [phase, setPhase] = useState<Phase>("intro");
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const [discoverResult, setDiscoverResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [discoverPollResult, setDiscoverPollResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [transactionId, setTransactionId] = useState("");
  const [patientMatches, setPatientMatches] = useState<PatientMatch[]>([]);
  // KEYED ON (visit, record type), NOT ON THE VISIT ALONE. The old set held
  // bare careContextReferences, and because ABDM lists the same visit under
  // every hiType it holds, ticking it in one section silently ticked it in
  // all the others -- and there was no way to link only the Prescription
  // from a visit. The compound key is what makes each row mean one thing.
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  /** Visits whose record-type list is expanded. Collapsed by default. */
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const [linkInitResult, setLinkInitResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [linkInitPollResult, setLinkInitPollResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [linkRefNumber, setLinkRefNumber] = useState("");

  const [otp, setOtp] = useState("");
  const [confirmResult, setConfirmResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [confirmPollResult, setConfirmPollResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [confirmedCount, setConfirmedCount] = useState(0);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  /** The one polling loop, reused for all three stages. `onRow` decides what to do with each fresh poll -- returning true means "still pending, keep polling." */
  const pollForResult = async (
    requestId: string,
    setPollResult: (result: ApiResult<AbdmPassthrough>) => void,
    onSettled: (row: PolledRow) => void,
    onTimeout: () => void,
  ): Promise<void> => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      await sleep(POLL_INTERVAL_MS);
      const result = await getUilResult(requestId);
      setPollResult(result);
      const row = extractPolledRow(result.data?.body ?? null);
      if (row !== null && row.status !== "PENDING") {
        onSettled(row);
        return;
      }
    }
    onTimeout();
  };

  if (sessionToken === "" || sessionAddress === "") {
    return (
      <section>
        <PageHeader icon={Link2} title="Link a facility" />
        <p className="muted">Log in first (Password or Mobile/OTP login) to link a new facility.</p>
      </section>
    );
  }

  const startDiscover = (): void => {
    void run(async () => {
      setErrorMessage("");
      const result = await uilDiscover({ xToken: sessionToken, hipId, abhaAddress: sessionAddress });
      setDiscoverResult(result);
      const requestId = result.data?.requestId;
      if (result.data?.ok !== true || !requestId) {
        setErrorMessage(
          describeRequestError(result.data?.body)
            || result.data?.error
            || "Couldn't start discovery — check the Console for details.",
        );
        return;
      }
      setPhase("discovering");
      await pollForResult(
        requestId,
        setDiscoverPollResult,
        (row) => {
          const callbackError = extractCallbackError(row.detail);
          if (callbackError !== null) {
            setErrorMessage(callbackError);
            setPhase("intro");
            return;
          }
          const txn = stringField(row.detail, "transactionId");
          const matches = extractPatientMatches(row.detail);
          setTransactionId(txn);
          setPatientMatches(matches);
          // Default: every discovered care context selected, per the task
          // spec's own "link all" as the simple default action -- the
          // patient can still deselect individual ones on the review step.
          // Everything on by default, per (visit, record type).
          setSelectedItems(new Set(
            matches.flatMap((m) => m.careContexts.map((cc) => itemKey(cc.referenceNumber, m.hiType))),
          ));
          setPhase("review");
        },
        () => setPhase("discover_timeout"),
      );
    });
  };

  /** One record type of one visit. */
  const toggleItem = (reference: string, hiType: string): void => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      const key = itemKey(reference, hiType);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /** The whole visit: selects all its record types, or clears them all. */
  const toggleEncounter = (group: EncounterGroup): void => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      const keys = group.items.map((i) => itemKey(group.reference, i.hiType));
      const allOn = keys.every((k) => next.has(k));
      for (const k of keys) {
        if (allOn) next.delete(k);
        else next.add(k);
      }
      return next;
    });
  };

  const toggleExpanded = (reference: string): void => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(reference)) next.delete(reference);
      else next.add(reference);
      return next;
    });
  };

  const startLinkInit = (): void => {
    void run(async () => {
      setErrorMessage("");
      const selectedPatientPayload = buildSelectedPatientPayload(patientMatches, selectedItems);
      const result = await uilLinkInit({
        xToken: sessionToken,
        hipId,
        transactionId,
        abhaAddress: sessionAddress,
        patientMatches: selectedPatientPayload,
      });
      setLinkInitResult(result);
      const requestId = result.data?.requestId;
      if (result.data?.ok !== true || !requestId) {
        setErrorMessage(result.data?.error || "Couldn't start linking — check the Console for details.");
        setPhase("review");
        return;
      }
      setPhase("linking");
      await pollForResult(
        requestId,
        setLinkInitPollResult,
        (row) => {
          const callbackError = extractCallbackError(row.detail);
          if (callbackError !== null) {
            setErrorMessage(callbackError);
            setPhase("review");
            return;
          }
          setLinkRefNumber(row.linkRefNumber || "");
          setPhase("otp");
        },
        () => setPhase("link_timeout"),
      );
    });
  };

  const startConfirm = (): void => {
    void run(async () => {
      setErrorMessage("");
      const otpNumber = Number(otp);
      if (!Number.isFinite(otpNumber)) {
        setErrorMessage("OTP must be numeric.");
        return;
      }
      const result = await uilLinkConfirm({
        xToken: sessionToken,
        hipId,
        abhaAddress: sessionAddress,
        token: otpNumber,
        linkRefNumber,
      });
      setConfirmResult(result);
      const requestId = result.data?.requestId;
      if (result.data?.ok !== true || !requestId) {
        setErrorMessage(result.data?.error || "Couldn't confirm the link — check the Console for details.");
        setPhase("otp");
        return;
      }
      setPhase("confirming");
      await pollForResult(
        requestId,
        setConfirmPollResult,
        (row) => {
          const callbackError = extractCallbackError(row.detail);
          if (callbackError !== null) {
            setErrorMessage(callbackError);
            setPhase("otp");
            return;
          }
          const linked = extractPatientMatches(row.detail);
          setConfirmedCount(linked.reduce((total, m) => total + m.careContexts.length, 0));
          // Tell HomeScreen records are inbound, so it watches for them
          // every few seconds instead of every thirty and says so on
          // screen. See recentLink.ts for why the gap matters.
          markRecentLink(hipId, hipName);
          setPhase("done");
        },
        () => setPhase("confirm_timeout"),
      );
    });
  };

  const encounterGroups = groupByEncounter(patientMatches);
  const selectedCount = selectedItems.size;
  // Visits with at least one record type selected -- what the patient
  // thinks of as "how many visits am I linking".
  const selectedEncounterCount = encounterGroups.filter((g) =>
    g.items.some((i) => selectedItems.has(itemKey(g.reference, i.hiType))),
  ).length;

  return (
    <section>
      <PageHeader
        icon={Link2}
        title="Link a facility"
        description={hipName}
        actions={
          <Button size="sm" icon={ArrowLeft} onClick={() => navigate("/providers")}>
            Back to Providers
          </Button>
        }
      />

      {errorMessage !== "" && (
        <Callout tone="warning" icon={AlertTriangle}>
          {errorMessage}
        </Callout>
      )}

      {phase === "intro" && (
        <Card padding="md">
          <CardBody>
            <CardTitle icon={Building2}>{hipName}</CardTitle>
            <p className="muted">
              Looks for care contexts already at this facility that aren&apos;t linked to your account
              yet. This is a read-only lookup — nothing is linked until you review the results and
              confirm.
            </p>
            <Button variant="primary" icon={Search} disabled={busy} onClick={startDiscover}>
              {busy ? "Starting…" : "Find my records here"}
            </Button>
            <RawBody label="uil/discover" result={discoverResult} />
          </CardBody>
        </Card>
      )}

      {phase === "discovering" && (
        <Callout icon={Loader2}>
          <p style={{ margin: 0 }}>Asking {hipName} what records they have for you — this can take a few seconds…</p>
        </Callout>
      )}

      {phase === "discover_timeout" && (
        <Callout tone="warning" icon={AlertTriangle}>
          <p style={{ margin: 0 }}>
            No answer from {hipName} after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000)}{" "}
            seconds. This does <strong>not</strong> mean it failed — the facility may just be slow.
          </p>
          <Button size="sm" icon={RefreshCw} onClick={startDiscover}>Try again</Button>
        </Callout>
      )}

      {phase === "review" && (
        <Card padding="md">
          <CardBody>
            <CardTitle icon={FileText}>Records found at {hipName}</CardTitle>
            {patientMatches.length === 0 ? (
              <EmptyState icon={Search} message="No care contexts were found for your ABHA address at this facility." />
            ) : (
              <>
                <p className="muted">
                  One section per visit. Everything is selected by default — untick a whole visit,
                  or open it to choose individual records.
                </p>
                {/* ONE SECTION PER VISIT, not per record type. ABDM sends
                    these grouped by hiType, which repeats the same visit
                    under every type it holds; groupByEncounter() inverts
                    that so the list matches how a patient remembers their
                    own care. */}
                {encounterGroups.map((group) => {
                  const keys = group.items.map((i) => itemKey(group.reference, i.hiType));
                  const selectedHere = keys.filter((k) => selectedItems.has(k)).length;
                  const allOn = selectedHere === keys.length && keys.length > 0;
                  const isOpen = expanded.has(group.reference);
                  return (
                    <Card key={group.reference} padding="sm" className="ui-card--flush">
                      <CardBody>
                        <label className="ui-list-row" style={{ cursor: "pointer", alignItems: "flex-start" }}>
                          <input
                            type="checkbox"
                            checked={allOn}
                            // Partially-selected reads as neither on nor
                            // off, which is the truth and stops a half
                            // selection looking like a full one.
                            ref={(el) => { if (el) el.indeterminate = selectedHere > 0 && !allOn; }}
                            onChange={() => toggleEncounter(group)}
                          />
                          <span className="ui-list-row__label">
                            <strong>{group.title}</strong>
                            {group.date !== "" && <span className="muted"> · {group.date}</span>}
                            <br />
                            <span className="muted" style={{ fontSize: "0.85em" }}>
                              {selectedHere} of {group.items.length} record
                              {group.items.length === 1 ? "" : "s"} selected
                            </span>
                          </span>
                        </label>

                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => toggleExpanded(group.reference)}
                        >
                          {isOpen ? "Hide records" : `Choose records (${group.items.length})`}
                        </Button>

                        {isOpen && (
                          <div style={{ marginTop: 8, marginLeft: 24 }}>
                            {group.items.map((item) => (
                              <label
                                key={item.hiType}
                                className="ui-list-row"
                                style={{ cursor: "pointer" }}
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedItems.has(itemKey(group.reference, item.hiType))}
                                  onChange={() => toggleItem(group.reference, item.hiType)}
                                />
                                <span className="ui-list-row__label">
                                  <Badge tone="info">{item.hiType}</Badge>
                                </span>
                              </label>
                            ))}
                          </div>
                        )}
                      </CardBody>
                    </Card>
                  );
                })}
                <Callout tone="warning" icon={Send}>
                  Linking will send a <strong>real OTP</strong> to your registered mobile via {hipName}.
                </Callout>
                <Button variant="primary" icon={Link2} disabled={busy || selectedCount === 0} onClick={startLinkInit}>
                  {busy
                    ? "Starting…"
                    : `Link ${selectedCount} record${selectedCount === 1 ? "" : "s"} from ${selectedEncounterCount} visit${selectedEncounterCount === 1 ? "" : "s"}`}
                </Button>
              </>
            )}
            <RawBody label="uil/discover result" result={discoverPollResult} />
          </CardBody>
        </Card>
      )}

      {phase === "linking" && (
        <Callout icon={Loader2}>
          <p style={{ margin: 0 }}>Asking {hipName} to send a one-time password to your registered mobile…</p>
        </Callout>
      )}

      {phase === "link_timeout" && (
        <Callout tone="warning" icon={AlertTriangle}>
          <p style={{ margin: 0 }}>
            No answer from {hipName} after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000)}{" "}
            seconds. This does <strong>not</strong> mean it failed — an OTP may still arrive. Wait a
            moment before trying again, to avoid a second SMS.
          </p>
          <Button size="sm" icon={RefreshCw} onClick={() => setPhase("review")}>Back to review</Button>
        </Callout>
      )}

      {phase === "otp" && (
        <Card padding="md">
          <CardBody>
            <CardTitle icon={Send}>Enter the OTP</CardTitle>
            <p className="muted">{hipName} sent a one-time password to your registered mobile.</p>
            <input
              type="password"
              value={otp}
              autoComplete="one-time-code"
              placeholder="Enter OTP"
              onChange={(event) => setOtp(event.target.value)}
            />
            <Button variant="primary" icon={Check} disabled={busy || otp === ""} onClick={startConfirm} style={{ marginTop: "var(--space-3)" }}>
              {busy ? "Confirming…" : "Confirm link"}
            </Button>
            <RawBody label="uil/link-init result" result={linkInitPollResult} />
          </CardBody>
        </Card>
      )}

      {phase === "confirming" && (
        <Callout icon={Loader2}>
          <p style={{ margin: 0 }}>Confirming with {hipName}…</p>
        </Callout>
      )}

      {phase === "confirm_timeout" && (
        <Callout tone="warning" icon={AlertTriangle}>
          <p style={{ margin: 0 }}>
            No answer from {hipName} after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000)}{" "}
            seconds confirming the link. This does <strong>not</strong> mean it failed.
          </p>
          <Button size="sm" icon={RefreshCw} onClick={() => setPhase("otp")}>Back to OTP entry</Button>
        </Callout>
      )}

      {phase === "done" && (
        <Card padding="md">
          <CardBody>
            <EmptyState
              icon={CheckCircle2}
              message={`Linked ${confirmedCount} record${confirmedCount === 1 ? "" : "s"} from ${hipName}. They'll appear in My Health Records on Home.`}
              action={
                <Button variant="primary" icon={ArrowLeft} onClick={() => navigate("/home")}>
                  Go to Home
                </Button>
              }
            />
            <RawBody label="uil/link-confirm result" result={confirmPollResult} />
          </CardBody>
        </Card>
      )}

      <RawBody label="uil/link-init" result={linkInitResult} />
      <RawBody label="uil/link-confirm" result={confirmResult} />
    </section>
  );
}
