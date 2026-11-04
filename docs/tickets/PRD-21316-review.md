# PRD-21316 · Code review

Status: frozen @ b0c5d98

## Round 1 · 2026-11-04 · reviewed b0c5d98 (base 5e8b8fb)

Verdict: approved

### Findings

1. [suggestion] src/posthog_mcp/client.py:16-19,62-90 — `MAX_RETRIES=3` with timeouts of 5s connect / 30s read means a pathological all-timeout run (4 attempts x up to 35s + ~7s total backoff) could approach ~147s, above the SOP §14 guideline of "single call total time < 120s". Not blocking: this only triggers if every attempt times out (a degenerate case), and the SOP item is advisory ("应当"), not an AC. Worth tightening (lower per-attempt read timeout or `MAX_RETRIES`) in a follow-up if PostHog proves slow in practice.

### Verification performed

- `uv sync` (82 packages, clean) and `uv run pytest -q` independently re-run on `b0c5d98`: 33 passed, 0 failed — matches the `[DEV]` stub's claim.
- Chinese-character scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): no output.
- Started the server locally (`uv run python -m posthog_mcp`) and independently verified: `GET /health` -> `200 {"status":"ok"}`; `POST /mcp tools/list` with no headers -> `401 not_configured` naming both headers; `POST /mcp tools/list` with placeholder headers and **no prior `initialize`** -> `200` with exactly 9 tools, confirming `stateless_http=True` holds end-to-end (not just claimed).
- README "MSPbots Connector" section diffed programmatically against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md`: byte-identical.
- Read the installed `mcp` SDK's `TransportSecurityMiddleware.__init__` (`.venv/lib/python3.15/site-packages/mcp/server/transport_security.py:48-50`) to independently confirm `app.py`'s documented claim that DNS-rebinding protection is disabled by default when no `TransportSecuritySettings` is passed — claim holds, not just asserted.
- `docker build --platform linux/amd64`: not run — this sandbox also lacks Docker daemon access (`permission denied ... docker.sock`), same environment limitation the dev leg already flagged. `Dockerfile` is a straight copy of the SOP's reference multi-stage template (non-root production user, `curl` installed, `EXPOSE 8080`, `HEALTHCHECK` on `/health`) — reviewed statically, no deviation found.
- Diff scope (`git diff 5e8b8fb...b0c5d98 --stat`): 25 files, all new, all within the designed change list (no extraneous files).
- Read every tool module (`feature_flags.py`, `insights.py`, `events.py`, `persons.py`, `cohorts.py`, `annotations.py`) against the tech design's "Data & API contract" table: endpoints, params, and response shaping match. `posthog_list_cohorts`'s client-side `type` filter (PostHog has no native query param for it) correctly derives `has_more`/`next_offset` from the upstream page's own `next` field before filtering, not from the post-filter item count — pagination stays correct even though filtering happens client-side (verified by reading `_shared.list_result` and `tools/cohorts.py` together, not just by the passing test).
- AC1..AC13 cross-checked one-by-one against `tests/test_tools.py` / `tests/test_middleware.py` and `docs/tickets/PRD-21316.ac.json`: every AC has at least one `pass`ed auto case or an explicitly-flagged non-blocking manual case (needs a real vendor account), consistent with the SOP's "no test account is not a blocker" rule.
- Credential/isolation path (`middleware.py` -> `ContextVar` -> `_shared.execute` -> `PostHogClient`) read end-to-end: no module-level or global variable holds a credential anywhere in the repo; `PostHogClient` is constructed fresh per tool call and closed in `__aexit__`; no cross-request caching.

No must-fix. Approved as-is.
