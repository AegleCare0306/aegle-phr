/**
 * Connection status, with three states a tester must be able to tell apart:
 *
 *   unreachable   nothing answered   -> tunnel down / wrong URL / CORS
 *   unauthorized  401                -> stale or wrong key
 *   reachable     200                -> plus whether the database is up
 *
 * A stale key is the single most likely failure once links have been handed
 * out, so it must never surface as a generic "something went wrong".
 */

import { HelpCircle, RefreshCw, ShieldAlert, Wifi, WifiOff } from "lucide-react";

import { Button } from "./ui/Button";
import type { ConnectionStatus } from "../useConnection";

interface Props {
  status: ConnectionStatus;
  onRecheck: () => void;
  busy: boolean;
}

export function StatusIndicator({ status, onRecheck, busy }: Props): JSX.Element {
  const { kind, detail } = status;

  const label =
    kind === "reachable" ? "Reachable"
    : kind === "unauthorized" ? "Unauthorized"
    : kind === "unreachable" ? "Unreachable"
    : "Not checked";

  const Icon =
    kind === "reachable" ? Wifi
    : kind === "unauthorized" ? ShieldAlert
    : kind === "unreachable" ? WifiOff
    : HelpCircle;

  return (
    <div className={`status status--${kind}`}>
      <span className="status__icon"><Icon size={16} aria-hidden="true" /></span>
      <span className="status__label">{label}</span>
      <span className="status__detail">{detail}</span>
      <Button variant="secondary" size="sm" icon={RefreshCw} onClick={onRecheck} disabled={busy}>
        {busy ? "Checking…" : "Re-check"}
      </Button>
    </div>
  );
}
