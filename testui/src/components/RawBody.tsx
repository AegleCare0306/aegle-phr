/**
 * Shared "raw ABDM response" block -- previously duplicated verbatim
 * across six screens (OtpLoginScreen, MobileLoginScreen,
 * PasswordLoginScreen, ProfileScreen, AadhaarRegisterScreen,
 * AbhaAddressCreationScreen), matching this project's own established
 * per-screen-helper convention. Consolidated here specifically so
 * Aayush's global show/hide raw-responses toggle (rawVisibility.ts) has
 * exactly ONE place to enforce -- "no exceptions" was the explicit
 * requirement, and six separate gated copies could silently drift.
 */

import { useState, useSyncExternalStore } from "react";
import { ChevronDown, ChevronRight, FileJson } from "lucide-react";

import type { AbdmPassthrough, ApiResult } from "../api/types";
import { getShowRawResponses, subscribeShowRawResponses } from "../rawVisibility";

/**
 * Collapsible per instance (defaults OPEN, matching the previous always-
 * shown behaviour) -- the "developer panel" look this chunk asked for,
 * without hiding anything by default that a tester relied on seeing.
 */
export function RawBody({ label, result }: { label: string; result: ApiResult<AbdmPassthrough> | null }): JSX.Element | null {
  const showRaw = useSyncExternalStore(subscribeShowRawResponses, getShowRawResponses, getShowRawResponses);
  const [open, setOpen] = useState(true);
  if (!showRaw || result === null) return null;
  const payload = result.data ?? { error: result.errorMessage, status: result.status };
  return (
    <div className="field field--block ui-raw-body">
      <button type="button" className="ui-raw-body__toggle" onClick={() => setOpen((prev) => !prev)} aria-expanded={open}>
        {open ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
        <FileJson size={13} aria-hidden="true" />
        <span className="field__label">{label} — raw ABDM response</span>
      </button>
      {open && <pre className="field__value">{JSON.stringify(payload, null, 2)}</pre>}
    </div>
  );
}
