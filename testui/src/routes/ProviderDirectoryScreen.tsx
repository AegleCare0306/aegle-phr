/**
 * Provider Directory -- all-providers / provider-by-id / govt-programs
 * (spec §10.3.13-15). The simplest chunk in this project: three
 * stateless, read-only GETs, no patient session token, no encryption,
 * and the spec/Postman agreed with each other on everything -- no
 * gap-filling judgment calls needed, unlike Consent. Built AFTER the
 * design-overhaul chunk had already landed, so this screen uses its
 * shared primitives (Card/Button/PageHeader/EmptyState/CardGrid/Badge)
 * from day one rather than needing a restyle later.
 *
 * Its own screen, not inline on Home -- same reasoning as Consent
 * getting its own screen: a distinct, self-contained feature, reachable
 * from the signed-in nav.
 *
 * LIVE-CONFIRMED, 2026-09-01 (ran the real backend locally against the
 * ABDM sandbox directly, bypassing the frontend, to settle the open
 * questions the task prompt flagged):
 *   - Authorization (gateway bearer) is NOT rejected -- every call
 *     returned 200 with it present. No evidence it's unneeded either;
 *     left in per the safe-default convention, exactly as planned.
 *   - An EMPTY name (`name: ""`) is NOT rejected -- ABDM returns 200
 *     with a full unfiltered list ("Doctor Automation One" entries, in
 *     the sandbox). No fallback-to-"require one character" logic was
 *     needed -- this screen fetches with an empty name on mount.
 *   - A name matching nothing returns 200 with a genuinely empty array
 *     (`body: []`), not an error -- EmptyState renders cleanly for this
 *     case, confirmed.
 *   - Provider-by-id's response really IS a strict subset of the search
 *     result's own per-item shape live (confirmed against a real
 *     "TestSJ199" lookup: no isGovtEntity/endpoints in the by-id
 *     response, present in the search response) -- and since the search
 *     response already carries everything the by-id endpoint documents,
 *     NO separate "view full detail" fetch was built (the task prompt's
 *     own "don't over-build this if the two shapes turn out identical"
 *     case) -- every card just expands in place using data already on
 *     hand from the search response.
 *
 * Every parser below is defensive and falls back to the shared RawBody
 * dump if a response ever doesn't match the confirmed shape, same
 * convention as every other module in this app.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, HeartHandshake, Landmark, Link2, RefreshCw, Search } from "lucide-react";

import { getGovtPrograms, searchProviders } from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Badge } from "../components/ui/Badge";
import type { BadgeTone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardFooter, CardTitle } from "../components/ui/Card";
import { CardGrid } from "../components/ui/CardGrid";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";

function objField(body: unknown, key: string): Record<string, unknown> {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (value !== null && typeof value === "object") return value as Record<string, unknown>;
  }
  return {};
}

interface ProviderSummary {
  name: string;
  id: string;
  facilityType: string[];
  isHIP: boolean | null;
  isGovtEntity: boolean | null;
}

/** Shared per-item reader for all three endpoints -- search/govt-programs are arrays of this shape, provider-by-id is one bare object of it. */
function extractProviderItem(item: unknown): ProviderSummary | null {
  if (item === null || typeof item !== "object") return null;
  const identifier = objField(item, "identifier");
  const record = item as Record<string, unknown>;
  const facilityType = record.facilityType;
  const isHIP = record.isHIP;
  const isGovtEntity = record.isGovtEntity;
  return {
    name: typeof identifier.name === "string" ? identifier.name : "",
    id: typeof identifier.id === "string" ? identifier.id : "",
    facilityType: Array.isArray(facilityType) ? facilityType.filter((f): f is string => typeof f === "string") : [],
    isHIP: typeof isHIP === "boolean" ? isHIP : null,
    isGovtEntity: typeof isGovtEntity === "boolean" ? isGovtEntity : null,
  };
}

/** #1 (search) and #3 (govt-programs) are both bare arrays -- confirmed live for both. */
function extractProviderList(body: unknown): ProviderSummary[] | null {
  if (!Array.isArray(body)) return null;
  const out: ProviderSummary[] = [];
  for (const item of body) {
    const parsed = extractProviderItem(item);
    if (parsed !== null) out.push(parsed);
  }
  return out;
}

function facilityTypeTone(facilityType: string): BadgeTone {
  if (facilityType === "HIP") return "info";
  if (facilityType === "HIU") return "success";
  if (facilityType === "HEALTH_LOCKER") return "neutral";
  return "neutral";
}

/**
 * `onLink` is only ever passed for search results, not Government
 * Programs -- P15's "Find my records" flow links care contexts at a real
 * HIP, not an enrollment in a government scheme, so the action only makes
 * sense for the former. Renders as a CardFooter's own solid primary
 * button, per P14's own hierarchy (one dominant action per card, nothing
 * competing with it).
 */
function ProviderCard({ provider, onLink }: { provider: ProviderSummary; onLink?: (provider: ProviderSummary) => void }): JSX.Element {
  return (
    <Card padding="sm">
      <CardTitle icon={Building2}>{provider.name || "Unnamed provider"}</CardTitle>
      <CardBody>
        <p className="ui-card__label">Provider ID</p>
        <p className="ui-card__value"><code>{provider.id || "—"}</code></p>
        <div className="suggestions">
          {provider.facilityType.length === 0 && <span className="muted">No facility type listed</span>}
          {provider.facilityType.map((facilityType) => (
            <Badge key={facilityType} tone={facilityTypeTone(facilityType)} icon={Building2}>
              {facilityType}
            </Badge>
          ))}
          {provider.isGovtEntity === true && (
            <Badge tone="warning" icon={Landmark}>Govt entity</Badge>
          )}
        </div>
      </CardBody>
      {onLink !== undefined && provider.id !== "" && (
        <CardFooter>
          <Button variant="primary" size="sm" icon={Link2} onClick={() => onLink(provider)}>
            Link this facility
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

export function ProviderDirectoryScreen(): JSX.Element {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [searchResult, setSearchResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [govtResult, setGovtResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  /** Whether a real search has actually been run yet -- distinct from
   * searchResult being null, so the screen can show a "search for
   * something" prompt first, never a bare empty grid. */
  const [hasSearched, setHasSearched] = useState(false);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  /**
   * P14 follow-up (2026-09-04, Aayush's own report): this used to fetch
   * with an empty name on mount, and ABDM does NOT reject that -- it
   * returns its full, unfiltered global directory (hundreds+ of HIPs/
   * HIUs/lockers), which this screen then rendered as one giant CardGrid.
   * That's the actual hang, not a slow network call: fetching AND
   * rendering "every provider ABDM knows about" on page load, every time.
   *
   * Fixed at the source rather than just moving the trigger from mount to
   * the Search button -- an empty-name search from the button would hit
   * the exact same unfiltered response. So: no fetch at all (mount or
   * button) without a real, non-empty name typed first. A blank field and
   * a name matching nothing now look different on purpose (see the empty
   * states below) -- "type something" vs. "that matched zero providers".
   */
  const search = async (): Promise<void> => {
    const trimmed = name.trim();
    if (trimmed === "") return;
    setHasSearched(true);
    setSearchResult(await searchProviders({ name: trimmed }));
  };

  const fetchGovtPrograms = async (): Promise<void> => {
    setGovtResult(await getGovtPrograms());
  };

  // Government Programs is a separate, small, fixed reference list (not
  // "every facility ABDM knows about"), so it keeps the original
  // "loads on mount, nothing to press" convention -- only Search Providers
  // had the unbounded-list problem.
  useEffect(() => {
    void run(fetchGovtPrograms);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const providers = extractProviderList(searchResult?.data?.body ?? null);
  const govtPrograms = extractProviderList(govtResult?.data?.body ?? null);

  return (
    <section className="panel">
      <PageHeader
        icon={Building2}
        title="Provider Directory"
        description="Search ABDM's global directory of HIPs, HIUs, and health lockers. Read-only -- nothing here links or requests anything."
      />

      <Card as="fieldset" disabled={busy} padding="md" style={{ marginBottom: "var(--space-4)" }}>
        <CardTitle icon={Search}>Search Providers</CardTitle>
        <label className="row">
          <span>Name</span>
          <input
            type="text"
            value={name}
            autoComplete="off"
            placeholder="e.g. test"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim() !== "") void run(search);
            }}
          />
        </label>
        <Button variant="primary" icon={Search} disabled={busy || name.trim() === ""} onClick={() => void run(search)}>
          Search
        </Button>
        <RawBody label="providers/search" result={searchResult} />

        {!hasSearched && (
          <EmptyState icon={Search} message="Type a facility, HIP, or HIU name above and press Search — this directory is too large to browse unfiltered." />
        )}

        {hasSearched && providers !== null && providers.length === 0 && (
          <EmptyState icon={Building2} message={`No providers matched "${name.trim()}".`} />
        )}

        {hasSearched && providers !== null && providers.length > 0 && (
          <CardGrid minWidth={260}>
            {providers.map((provider, index) => (
              <ProviderCard
                key={`${provider.id}-${index}`}
                provider={provider}
                onLink={(p) => navigate(`/link/${encodeURIComponent(p.id)}?name=${encodeURIComponent(p.name || p.id)}`)}
              />
            ))}
          </CardGrid>
        )}

        {searchResult?.data?.ok === true && providers === null && (
          <p className="muted">The response didn&apos;t match the expected shape (expected an array) — check the raw response above.</p>
        )}
      </Card>

      <Card as="fieldset" disabled={busy} padding="md">
        <CardTitle icon={Landmark}>Government Programs</CardTitle>
        <Button size="sm" icon={RefreshCw} disabled={busy} onClick={() => void run(fetchGovtPrograms)}>
          Refresh
        </Button>
        <RawBody label="providers/govt-programs" result={govtResult} />

        {govtPrograms !== null && govtPrograms.length === 0 && (
          <EmptyState icon={HeartHandshake} message="No government programs returned." />
        )}

        {govtPrograms !== null && govtPrograms.length > 0 && (
          <CardGrid minWidth={260}>
            {govtPrograms.map((program, index) => (
              <ProviderCard key={`${program.id}-${index}`} provider={program} />
            ))}
          </CardGrid>
        )}

        {govtResult?.data?.ok === true && govtPrograms === null && (
          <p className="muted">The response didn&apos;t match the expected shape (expected an array) — check the raw response above.</p>
        )}
      </Card>
    </section>
  );
}
