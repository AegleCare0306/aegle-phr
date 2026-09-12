# Claude Code prompt — P0-B follow-up: the three Docker-blocked checks

> Paste below the horizontal rule into Claude Code in `C:\Users\hp\Desktop\Aayush\aegle-phr`.
> **Recommended model: Sonnet.** Mechanical verification, no design decisions.

---

Docker Desktop is now installed. Run the three verification checks that were blocked in the previous chunk, plus two additions below.

This is **verification only**. Do not change any application code. If a check fails, report the failure and stop — do not fix it without telling me first. The only exception is the standing rule: if the failure is a bug you introduced in the previous chunk, fix that and say so.

## The checks

1. **Database up and migrated.** `docker compose up -d`, wait for the container's healthcheck to report healthy (don't just sleep — poll it), then `alembic upgrade head`. Show the output.

2. **Schema inspection.** Query `information_schema` / `pg_indexes` and show the actual result: every column of `callback_log` with its real type, and both indexes with their definitions. I want to see `jsonb` and `timestamp with time zone` in the database's own words, not in the migration file's.

3. **Health endpoint.** `GET /phr/health` returns 200 with `database: true`. Do this as a real HTTP round trip through `TestClient` (or a running server) — **not** by introspecting routes. You noted that FastAPI 0.139 stores included routers lazily as `_IncludedRouter`, so `app.routes` doesn't expose leaf paths; that's exactly why this must be an actual request.

4. **Real callback row.** With callback auth bypassed, POST a realistic payload to one of the six owned callback routes. Assert exactly one `callback_log` row is written and the payload round-trips intact.

5. **Prove the column is genuinely JSONB — this is new, and it matters.** A round-trip through a `TEXT` column would pass check 4 identically. So query the row back using a **JSON operator in SQL**, e.g. `SELECT payload->>'<some key>' FROM callback_log WHERE id = ...`, and show that it returns the expected value. If the column were TEXT, that query errors. Also confirm key order is not preserved (JSONB normalises) — that's the positive signal you're on `jsonb` and not `json`.

6. **Connection timeout didn't break the happy path — also new.** You added `connect_args={"connect_timeout": 5}` in the previous chunk. Confirm a normal connection to a healthy database still works with it in place (checks 1–5 passing covers this, so just state it explicitly rather than writing a separate test).

## Cleanup

Delete the `callback_log` row(s) you inserted once the checks pass, and show the table's final row count as `0`. Leave the schema, the migration, the container and its volume in place.

Delete the verification script itself. Do not leave it in the repo.

## Report

Show the real output of each check — the actual `information_schema` rows, the actual JSON operator result, the actual counts. Not a summary claiming they passed.

Then a short summary I can paste back into my Cowork session.

## Standing ground rules

1. No throwaway scripts left behind.
2. Detailed report of exactly what you ran and what it returned.
3. Strict scope discipline — verification only, no application code changes. Flag anything you spot, don't fix it.
4. No git commit, no git push, no `git init`.
5. Never delete or truncate existing `logs/` or `storage/` content.
6. Don't claim something works without running it.
7. Flag uncertainty visibly.
8. Do not modify `repo\` or `aegle-abdm-core\`.
