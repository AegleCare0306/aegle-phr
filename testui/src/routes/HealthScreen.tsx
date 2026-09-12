/**
 * The one working screen: GET /phr/health.
 *
 * Also the worked example for adding a screen -- see testui/README.md.
 * Note what it does NOT do: no fetch, no URL building, no header handling.
 * It calls an endpoint function and renders the result.
 */

import { useState } from "react";
import { Activity, Send } from "lucide-react";

import { getHealth } from "../api/endpoints";
import type { ApiResult, HealthResponse } from "../api/types";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";

export function HealthScreen(): JSX.Element {
  const [result, setResult] = useState<ApiResult<HealthResponse> | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (): Promise<void> => {
    setBusy(true);
    try {
      setResult(await getHealth());
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <PageHeader
        icon={Activity}
        title="Health"
        description="GET /phr/health"
        actions={
          <Button variant="primary" icon={Send} onClick={() => void run()} disabled={busy}>
            {busy ? "Calling…" : "Call"}
          </Button>
        }
      />

      {result === null ? (
        <p className="muted panel__empty">Not called yet.</p>
      ) : result.kind === "success" && result.data !== null ? (
        <dl className="result">
          <dt>status</dt><dd>{result.data.status}</dd>
          <dt>database</dt>
          <dd className={result.data.database ? "ok" : "bad"}>{String(result.data.database)}</dd>
          <dt>HTTP</dt><dd>{result.status}</dd>
        </dl>
      ) : (
        <p className="result result--error">
          {result.status !== null ? `HTTP ${result.status} — ` : ""}
          {result.errorMessage ?? "Request failed."}
        </p>
      )}

      <p className="muted">Full request and response are in the Console below.</p>
    </section>
  );
}
