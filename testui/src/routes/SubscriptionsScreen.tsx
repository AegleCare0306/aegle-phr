/**
 * P13 -- Subscription Flow (spec §8) patient-facing UI. Real nav entry
 * (App.tsx), not a hidden/dev-only route -- same standing UX directive
 * ConsentScreen.tsx's own Requests tab follows, and this screen mirrors
 * that one's picker/RawBody/run() patterns rather than inventing new ones.
 *
 * THREE SECTIONS, matching CC_PROMPT_P13_subscription_flow_full_build.md's
 * own UI requirements list:
 *   1. Self-Subscription -- the auto-approve-shaped case (8.3.2 with
 *      hiu.id=CLIENT_ID). Also fires automatically once per session from
 *      HomeScreen.tsx's own login effect, alongside ensureSelfViewAutoApprove()
 *      -- the button here is for manual re-trigger/visibility, not the
 *      only way it happens.
 *   2. Subscription Requests -- list (8.3.1) with Approve/Deny/Edit
 *      (8.3.4/8.3.7/8.3.9) for whichever ones need patient action.
 *   3. Health Lockers -- list (8.3.16), detail (8.3.17), Setup Locker
 *      (8.3.18) with the X-LOCKER-ID surfaced for debugging (R2 in the
 *      task spec -- whether CLIENT_ID is genuinely registered as a
 *      HEALTH_LOCKER is unconfirmed, resolved by trying it live, not by
 *      guessing silently).
 *
 * hiTypes ARE NOT part of 8.3.1's own response shape (spec's own example:
 * patient/purpose/hiu/hips/categories/period, no hiTypes at all) -- so
 * Approve's own form defaults to every hiType (same broad default
 * ConsentScreen.tsx's own Auto-Approve section uses) rather than trying
 * to infer a narrower set from data that isn't there.
 */

import { useState } from "react";
import {
  Bell,
  Check,
  Edit3,
  Lock,
  PlusCircle,
  RefreshCw,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";

import {
  approveSubscriptionRequest,
  denySubscriptionRequest,
  editSubscription,
  ensureSelfSubscription,
  getAllSubscriptionRequests,
  getLocalSubscriptions,
  getLockerDetails,
  getPatientSubscribedLockers,
  setupLocker,
} from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import type { BadgeTone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardTitle } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { getSessionAddress, getSessionToken } from "../session";

const HI_TYPES = [
  "Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
  "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
];

function statusBadge(status: string): { tone: BadgeTone; label: string } {
  const upper = status.toUpperCase();
  if (upper === "GRANTED") return { tone: "success", label: status };
  if (upper === "DENIED" || upper === "DENY" || upper === "REVOKED" || upper === "REVOKE") return { tone: "danger", label: status };
  if (upper === "REQUESTED") return { tone: "warning", label: status };
  return { tone: "neutral", label: status || "UNKNOWN" };
}

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

interface SubscriptionRequestRow {
  requestId: string;
  subscriptionId: string;
  requestType: string;
  status: string;
  patientId: string;
  hiuId: string;
  hiuName: string;
  categories: string[];
  periodFrom: string;
  periodTo: string;
}

/** Reads 8.3.1's own documented `{requests: [...]}` shape -- see subscription.py's own get_all_subscription_requests() docstring for the source. */
function extractSubscriptionRequests(body: unknown): SubscriptionRequestRow[] | null {
  if (body === null || typeof body !== "object" || !("requests" in body)) return null;
  const requests = (body as { requests: unknown }).requests;
  if (!Array.isArray(requests)) return null;

  return requests
    .filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    .map((item) => {
      const details = objField(item, "details");
      const hiu = objField(details, "hiu");
      const period = objField(details, "period");
      const categories = details.categories;
      return {
        requestId: stringField(item, "requestId"),
        subscriptionId: stringField(item, "subscriptionId"),
        requestType: stringField(item, "requestType"),
        status: stringField(item, "status"),
        patientId: stringField(objField(details, "patient"), "id"),
        hiuId: stringField(hiu, "id"),
        hiuName: stringField(hiu, "name"),
        categories: Array.isArray(categories) ? categories.filter((c): c is string => typeof c === "string") : [],
        periodFrom: stringField(period, "from"),
        periodTo: stringField(period, "to"),
      };
    });
}

interface LockerRow {
  lockerId: string;
  lockerName: string;
  isActive: boolean;
}

/** Reads 8.3.16's own documented bare-array shape. */
function extractLockers(body: unknown): LockerRow[] | null {
  if (!Array.isArray(body)) return null;
  return body
    .filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    .map((item) => ({
      lockerId: stringField(item, "lockerId"),
      lockerName: stringField(item, "lockerName"),
      isActive: item.isActive === true,
    }));
}

export function SubscriptionsScreen(): JSX.Element {
  const [sessionToken] = useState(() => getSessionToken());
  const [sessionAddress] = useState(() => getSessionAddress());
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  // --- Self-Subscription -----------------------------------------------
  const [ensureResult, setEnsureResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [localResult, setLocalResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const localSubscriptions = Array.isArray((localResult?.data?.body as { subscriptions?: unknown } | undefined)?.subscriptions)
    ? ((localResult?.data?.body as { subscriptions: Record<string, unknown>[] }).subscriptions)
    : null;

  const refreshLocal = (): void => {
    void run(async () => setLocalResult(await getLocalSubscriptions({ patientAbhaAddress: sessionAddress })));
  };

  // --- Subscription Requests ---------------------------------------------
  const [requestsResult, setRequestsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const requests = extractSubscriptionRequests(requestsResult?.data?.body ?? null);

  const fetchRequests = (): void => {
    void run(async () => setRequestsResult(await getAllSubscriptionRequests({ xToken: sessionToken, status: "ALL" })));
  };

  const [decisionResult, setDecisionResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [denyReasonByRequest, setDenyReasonByRequest] = useState<Record<string, string>>({});

  const approve = (row: SubscriptionRequestRow): void => {
    void run(async () => {
      const result = await approveSubscriptionRequest({
        xToken: sessionToken,
        subscriptionRequestId: row.requestId,
        isApplicableForAllHIPs: true,
        hiTypes: HI_TYPES,
        categories: row.categories.length > 0 ? row.categories : ["LINK", "DATA"],
        periodFrom: row.periodFrom || new Date().toISOString(),
        periodTo: row.periodTo || new Date(Date.now() + 100 * 365 * 24 * 60 * 60 * 1000).toISOString(),
      });
      setDecisionResult(result);
      if (result.data?.ok === true) fetchRequests();
    });
  };

  const deny = (row: SubscriptionRequestRow): void => {
    const reason = denyReasonByRequest[row.requestId] ?? "";
    if (reason === "") return;
    void run(async () => {
      const result = await denySubscriptionRequest({ xToken: sessionToken, subscriptionRequestId: row.requestId, reason });
      setDecisionResult(result);
      if (result.data?.ok === true) fetchRequests();
    });
  };

  const [editResult, setEditResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [editingSubscriptionId, setEditingSubscriptionId] = useState<string>("");
  const [editPeriodFrom, setEditPeriodFrom] = useState("");
  const [editPeriodTo, setEditPeriodTo] = useState("");

  const submitEdit = (row: SubscriptionRequestRow): void => {
    void run(async () => {
      const result = await editSubscription({
        xToken: sessionToken,
        approvedSubscriptionId: row.subscriptionId || row.requestId,
        hiuId: row.hiuId,
        isApplicableForAllHIPs: true,
        hiTypes: HI_TYPES,
        categories: row.categories.length > 0 ? row.categories : ["LINK", "DATA"],
        periodFrom: editPeriodFrom || row.periodFrom,
        periodTo: editPeriodTo || row.periodTo,
      });
      setEditResult(result);
      if (result.data?.ok === true) {
        setEditingSubscriptionId("");
        fetchRequests();
      }
    });
  };

  // --- Health Lockers -----------------------------------------------------
  const [lockersResult, setLockersResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const lockers = extractLockers(lockersResult?.data?.body ?? null);

  const fetchLockers = (): void => {
    void run(async () => setLockersResult(await getPatientSubscribedLockers({ xToken: sessionToken, includeInactive: true })));
  };

  const [lockerDetailResult, setLockerDetailResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const viewLockerDetails = (lockerId: string): void => {
    void run(async () => setLockerDetailResult(await getLockerDetails({ xToken: sessionToken, lockerId })));
  };

  const [setupLockerId, setSetupLockerId] = useState("");
  const [setupLockerResult, setSetupLockerResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const submitSetupLocker = (): void => {
    if (setupLockerId === "") return;
    void run(async () => {
      const result = await setupLocker({ xToken: sessionToken, lockerId: setupLockerId });
      setSetupLockerResult(result);
    });
  };

  if (sessionToken === "") {
    return (
      <section className="panel">
        <PageHeader icon={Bell} title="Subscriptions" />
        <p className="muted">Log in first to manage subscriptions.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <PageHeader icon={Bell} title="Subscriptions" description="Spec §8 -- get notified when new records show up, without checking manually." />

      {/* --- Self-Subscription --------------------------------------- */}
      <Card as="fieldset" disabled={busy} padding="md" style={{ marginBottom: "var(--space-4)" }}>
        <CardTitle icon={ShieldCheck}>Self-Subscription</CardTitle>
        <p className="muted">
          Also fires automatically once per login (same as Consent Auto-Approve) -- this button is for
          manual re-trigger/visibility, not the only way it happens.
        </p>
        <Button size="sm" icon={Send} onClick={() => void run(async () => setEnsureResult(await ensureSelfSubscription({ patientAbhaAddress: sessionAddress })))}>
          Ensure Self-Subscription
        </Button>
        <RawBody label="ensure-self-subscription" result={ensureResult} />
        <Button size="sm" icon={RefreshCw} onClick={refreshLocal}>Refresh local status</Button>
        <RawBody label="get-local" result={localResult} />
        {localSubscriptions !== null && (
          <ul>
            {localSubscriptions.map((row) => {
              const badge = statusBadge(typeof row.status === "string" ? row.status : "");
              return (
                <li key={String(row.requestId)}>
                  <Badge tone={badge.tone}>{badge.label}</Badge>{" "}
                  requestId={String(row.requestId)} subscriptionRequestId={String(row.subscriptionRequestId ?? "—")} subscriptionId={String(row.subscriptionId ?? "—")}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* --- Subscription Requests ------------------------------------ */}
      <Card as="fieldset" disabled={busy} padding="md" style={{ marginBottom: "var(--space-4)" }}>
        <CardTitle icon={Bell}>Subscription Requests</CardTitle>
        <Button size="sm" icon={RefreshCw} onClick={fetchRequests}>Refresh</Button>
        <RawBody label="requests/get-all" result={requestsResult} />
        {requests !== null && requests.length === 0 && <p className="muted">No subscription requests yet.</p>}
        {requests !== null && requests.length > 0 && (
          <ul>
            {requests.map((row) => {
              const badge = statusBadge(row.status);
              const isRequested = row.status.toUpperCase() === "REQUESTED";
              const isGranted = row.status.toUpperCase() === "GRANTED";
              return (
                <li key={row.requestId} className="field field--block">
                  <div>
                    <Badge tone={badge.tone}>{badge.label}</Badge>{" "}
                    <strong>{row.hiuName || row.hiuId}</strong> — {row.categories.join(", ") || "—"} — patient {row.patientId}
                  </div>
                  <p className="muted">requestId={row.requestId} subscriptionId={row.subscriptionId || "—"}</p>

                  {isRequested && (
                    <>
                      <Button size="sm" icon={Check} onClick={() => approve(row)}>Approve (all hiTypes, {row.categories.join("+") || "LINK+DATA"})</Button>
                      <label className="row">
                        <span>Deny reason</span>
                        <input
                          type="text"
                          value={denyReasonByRequest[row.requestId] ?? ""}
                          onChange={(event) => setDenyReasonByRequest((prev) => ({ ...prev, [row.requestId]: event.target.value }))}
                        />
                      </label>
                      <Button size="sm" icon={X} disabled={(denyReasonByRequest[row.requestId] ?? "") === ""} onClick={() => deny(row)}>Deny</Button>
                    </>
                  )}

                  {isGranted && (
                    <>
                      {editingSubscriptionId !== row.requestId ? (
                        <Button size="sm" icon={Edit3} onClick={() => setEditingSubscriptionId(row.requestId)}>Edit date range</Button>
                      ) : (
                        <>
                          <label className="row">
                            <span>New period from</span>
                            <input type="text" value={editPeriodFrom} placeholder={row.periodFrom} onChange={(event) => setEditPeriodFrom(event.target.value)} />
                          </label>
                          <label className="row">
                            <span>New period to</span>
                            <input type="text" value={editPeriodTo} placeholder={row.periodTo} onChange={(event) => setEditPeriodTo(event.target.value)} />
                          </label>
                          <Button size="sm" icon={Send} onClick={() => submitEdit(row)}>Submit edit</Button>
                        </>
                      )}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <RawBody label="approve-or-deny" result={decisionResult} />
        <RawBody label="edit" result={editResult} />
      </Card>

      {/* --- Health Lockers --------------------------------------------- */}
      <Card as="fieldset" disabled={busy} padding="md">
        <CardTitle icon={Lock}>Health Lockers</CardTitle>
        <Button size="sm" icon={RefreshCw} onClick={fetchLockers}>Refresh</Button>
        <RawBody label="lockers/get-all" result={lockersResult} />
        {lockers !== null && lockers.length === 0 && <p className="muted">No subscribed lockers.</p>}
        {lockers !== null && lockers.length > 0 && (
          <ul>
            {lockers.map((locker) => (
              <li key={locker.lockerId}>
                <Badge tone={locker.isActive ? "success" : "neutral"}>{locker.isActive ? "ACTIVE" : "INACTIVE"}</Badge>{" "}
                {locker.lockerName || locker.lockerId} (lockerId={locker.lockerId}){" "}
                <Button size="sm" onClick={() => viewLockerDetails(locker.lockerId)}>Details</Button>
              </li>
            ))}
          </ul>
        )}
        <RawBody label="lockers/get-one" result={lockerDetailResult} />

        <p className="muted">
          R2 (open item): whether this bridge is genuinely registered as a HEALTH_LOCKER type is
          unconfirmed. X-LOCKER-ID is caller-supplied here, not guessed by the backend -- try your
          bridge id (SBXID_046112) first, and check the raw response below either way.
        </p>
        <label className="row">
          <span>X-LOCKER-ID</span>
          <input type="text" value={setupLockerId} placeholder="SBXID_046112" onChange={(event) => setSetupLockerId(event.target.value)} />
        </label>
        <Button size="sm" icon={PlusCircle} disabled={setupLockerId === ""} onClick={submitSetupLocker}>Setup Locker</Button>
        <RawBody label="setup-locker" result={setupLockerResult} />
      </Card>
    </section>
  );
}
