/**
 * Connection state, derived from a real /phr/health call rather than guessed
 * from whether a key happens to be present.
 */

import { useCallback, useState } from "react";

import { getHealth } from "./api/endpoints";

export type ConnectionKind = "unknown" | "reachable" | "unauthorized" | "unreachable";

export interface ConnectionStatus {
  kind: ConnectionKind;
  detail: string;
}

export interface UseConnection {
  status: ConnectionStatus;
  busy: boolean;
  check: () => Promise<void>;
}

export function useConnection(): UseConnection {
  const [status, setStatus] = useState<ConnectionStatus>({ kind: "unknown", detail: "No check run yet." });
  const [busy, setBusy] = useState(false);

  const check = useCallback(async (): Promise<void> => {
    setBusy(true);
    try {
      const result = await getHealth();

      if (result.kind === "success" && result.data !== null) {
        setStatus({
          kind: "reachable",
          detail: result.data.database ? "Backend up, database up." : "Backend up, DATABASE DOWN.",
        });
        return;
      }

      if (result.status === 401) {
        setStatus({ kind: "unauthorized", detail: "401 — the access key is missing or wrong. Re-open your link, or fix it in Settings." });
        return;
      }

      if (result.kind === "http-error") {
        setStatus({ kind: "unreachable", detail: `Backend answered ${result.status ?? "?"}: ${result.errorMessage ?? "unknown error"}` });
        return;
      }

      setStatus({ kind: "unreachable", detail: result.errorMessage ?? "Could not reach the backend." });
    } finally {
      setBusy(false);
    }
  }, []);

  return { status, busy, check };
}
