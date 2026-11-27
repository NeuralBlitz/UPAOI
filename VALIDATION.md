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
