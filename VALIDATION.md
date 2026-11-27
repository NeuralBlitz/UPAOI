# UPAOI MVP v0.3.0 — validation checkpoint

Date: 2026-11-27 (America/Chicago)

## Commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nb_orchestrator.cli demo --db :memory:
PYTHONPATH=src python -m nb_orchestrator.cli agents --db :memory:
python -m compileall -q src
```

## Local execution evidence

- **57/57 unit tests passed** in the source-tree environment (Python 3.13).
- Core DAG demo: `COMPLETED`, three deterministic local steps, 9 events.
- Two-specialist demo: `COMPLETED`, two separate registered workers plus reviewer callbacks, 7 events.
- Existing provider contract and synthetic GitHub/Notion fixture tests remain passing.

### New security regressions

- Principal A cannot replay principal B's completed request by guessing its request ID.
- Denied requests do not alter another run's completed status.
- Two live workers targeting the same unfinished request cannot both execute its adapter against the same SQLite database.
- An abandoned process claim is fail-closed, not automatically stolen.
- Legacy principal-less SQLite request rows cannot be replayed by arbitrary principals.
- Schema validation failures do not log full secret-bearing input payloads.
- Specialist workers cannot expand source references or classification scopes, bypass schema limits, mutate caller payloads, or approve their own result by claiming a reviewer identity.

- GitHub Actions workflow YAML validated using PyYAML, with a regression test guarding the smoke-test step.

## Explicit nonclaims

- Tests use local callbacks and mocked provider responses, not live LLM agents or live provider credentials.
- SQLite-exclusive claims are local to a shared database. They are **not** distributed fencing tokens or safe automatic crash recovery.
- `principal_id` does not authenticate an Internet user; only a trusted host may establish the caller's identity.
- Code is not yet merged into `main`, deployed, or accepted as production ready.
- GitHub-hosted CI for this commit remains unverified until the branch is pushed and the new workflow runs.


## v0.4.0 enterprise read-only gateway — 2026-11-27

- Local Python 3.13.5 editable installation, 86/86 tests, and source compilation passed.
- Initial hosted GitHub CI: [run #46080900625](https://github.com/NeuralBlitz/UPAOI/actions/runs/46080900625) succeeded on Python 3.10, 3.12, 3.13; subsequent documentation commits require their own new head check.
- Added signed RS256 OIDC verification, scoped tenant execution policy, server-defined P0-only workflow catalog, bounded FastAPI endpoint, HMAC-linked audit receipts, audit-verify CLI, concurrency regression tests, fail-closed startup, runbook, product milestone charter, and Dependabot configuration.
- No live identity provider or provider token was provisioned, no external tool writes, and no production deployment, multi-tenant isolation certification, or distributed recovery was performed.
- PR #3 is still subject to review before merge. Source: [Enterprise Pilot](docs/enterprise-pilot.md).


## v0.4.1 internal-alpha admission hardening

- Shared SQLite transaction limits for tenant and verified principal; denies
  are observable as `RUN_RATE_LIMITED` audit events without sensitive IDs.
- Runtime HTTP 429/`Retry-After`, readiness 503 on audit corruption or broken
  admission ledger, and ASGI threadpool execution to avoid event-loop blocking.
- Principal-bound request collision is reported as blocked/HTTP 409, not a 500.
- Audit checkpoint HMAC export and verification against independent stored
  anchors, including truncation/rollback tests.
- These checks use locally generated RSA keys and deterministic mock adapters.
  **No live cloud integration, operational HA, or production approval is implied.**

## M3 read-only identity/provider preflight v0.4.2

- Local suite: **114/114 tests passed** under Python 3.13 after editable install.
- `upaoi preflight --fixture --repo NeuralBlitz/UPAOI --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd`: **SIMULATED_ONLY**, no network calls or real identity verification.
- Configured-live preflight verifies a short-lived access token with pinned issuer/audience/JWKS and checks trusted tenant and both read scopes *before* external GETs.
- Provider identities and URLs are verified against operator allowlists. The receipt never returns source text, JWT claims, usernames or credential material.
- Negative-path unit tests cover missing credentials, forged/expired tokens, missing read scope, wrong tenant, source mismatch and sanitized provider exceptions.
- CI includes the offline fixture preflight. **No independently provisioned live IdP/GitHub/Notion credential exercise is claimed**.
