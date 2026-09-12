/**
 * Every HTTP call the harness has made, newest first, expandable.
 *
 * This panel gets screenshotted and pasted into chats, so the access key is
 * never shown -- it is already masked in the stored record (see client.ts),
 * not merely hidden here.
 */

import { useSyncExternalStore, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Copy, Inbox, Terminal, Trash2, WifiOff } from "lucide-react";

import { clearRecords, getRecords, subscribe } from "../api/consoleStore";
import type { ConsoleRecord } from "../api/types";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { PageHeader } from "./ui/PageHeader";

function pretty(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function outcomeClass(record: ConsoleRecord): string {
  if (record.error !== null && record.status === null) return "entry--network";
  if (record.status !== null && record.status >= 400) return "entry--error";
  return "entry--ok";
}

function OutcomeIcon({ record }: { record: ConsoleRecord }): JSX.Element {
  const cls = outcomeClass(record);
  if (cls === "entry--network") return <WifiOff size={14} aria-hidden="true" />;
  if (cls === "entry--error") return <AlertTriangle size={14} aria-hidden="true" />;
  return <CheckCircle2 size={14} aria-hidden="true" />;
}

function Entry({ record }: { record: ConsoleRecord }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = (): void => {
    void navigator.clipboard.writeText(JSON.stringify(record, null, 2)).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      },
      () => setCopied(false),
    );
  };

  const statusText = record.status === null ? "ERR" : String(record.status);

  return (
    <li className={`entry ${outcomeClass(record)}`}>
      <div className="entry__head">
        <button className="entry__toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
        </button>
        <span className="entry__outcome-icon"><OutcomeIcon record={record} /></span>
        <span className="entry__status">{statusText}</span>
        <span className="entry__method">{record.method}</span>
        <span className="entry__url" title={record.url}>{record.url}</span>
        <span className="entry__ms">{record.durationMs} ms</span>
        <Button size="sm" icon={Copy} onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
      </div>

      {open && (
        <div className="entry__body">
          <Field label="id" value={record.id} />
          <Field label="started at" value={record.startedAt} />
          <Field label="duration" value={`${record.durationMs} ms`} />
          <Field label="request headers" value={pretty(record.requestHeaders)} block />
          <Field label="request body" value={pretty(record.requestBody)} block />
          <Field label="status" value={record.status === null ? "null (no response)" : String(record.status)} />
          <Field label="response headers" value={pretty(record.responseHeaders)} block />
          <Field label="response body" value={pretty(record.responseBody)} block />
          <Field label="error" value={record.error ?? "null"} block />
        </div>
      )}
    </li>
  );
}

function Field({ label, value, block }: { label: string; value: string; block?: boolean }): JSX.Element {
  return (
    <div className={block === true ? "field field--block" : "field"}>
      <span className="field__label">{label}</span>
      <pre className="field__value">{value}</pre>
    </div>
  );
}

export function ConsolePanel(): JSX.Element {
  const records = useSyncExternalStore(subscribe, getRecords, getRecords);

  return (
    <section className="panel ui-dev-panel">
      <PageHeader
        icon={Terminal}
        title="Console"
        description={`${records.length} call${records.length === 1 ? "" : "s"} · in memory only`}
        actions={
          <Button size="sm" icon={Trash2} onClick={clearRecords} disabled={records.length === 0}>Clear</Button>
        }
      />

      {records.length === 0 ? (
        <EmptyState icon={Inbox} message="No requests yet. Every call the app makes appears here." />
      ) : (
        <ul className="entries">
          {records.map((record) => <Entry key={record.id} record={record} />)}
        </ul>
      )}
    </section>
  );
}
