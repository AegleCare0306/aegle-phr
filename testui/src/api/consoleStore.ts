/**
 * In-memory store of every HTTP call the harness has made.
 *
 * IN MEMORY ONLY, deliberately. Response bodies will contain OTPs, tokens
 * and patient identifiers once real flows land in P1. Nothing here goes to
 * localStorage; the only persisted values in this app are the backend URL
 * and the access key (see config.ts). A reload clears the console, and that
 * is the intended trade.
 *
 * A tiny hand-rolled store rather than a state library: one value, a few
 * subscribers, no dependency.
 */

import type { ConsoleRecord } from "./types";

/** Bounded so a long session cannot grow memory without limit. */
const MAX_RECORDS = 200;

let records: ConsoleRecord[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Newest first -- the entry a tester wants is almost always the last call. */
export function addRecord(record: ConsoleRecord): void {
  records = [record, ...records].slice(0, MAX_RECORDS);
  emit();
}

export function clearRecords(): void {
  records = [];
  emit();
}

export function getRecords(): ConsoleRecord[] {
  return records;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
