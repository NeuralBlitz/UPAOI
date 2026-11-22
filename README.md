# NeuralBlitz UPAOI — Executable Core MVP v0.2.0

A **local, permission-aware, deterministic orchestration prototype** implementing part of the NeuralBlitz *Universal Plugin and Agent Orchestration Intelligence* design.

Canonical blueprint: [NeuralBlitz UPAOI](https://app.notion.com/p/41325ca447c181ac82aee167d8fe80fd).

## What is implemented and tested

- Typed, versioned capability and agent contracts.
- Capability filtering by tags, risk class, health, explicit grants, and reliability.
- Deterministic DAG execution with dependency validation and typed step references.
- Fail-closed policy enforcement for scope, agent grants, schema drift, and P1/P2/P3 approvals.
- JSON Schema validation at the connector boundary.
- SQLite request ledger, append-only events, and durable *completed-step* checkpoints.
- Same request ID + same workflow specification skips completed steps.
- Required read-back verifier for permitted non-read operations.
- Zero network access and zero external write calls in the supplied demonstration.

## New in v0.2.0 — safe provider integration slice

- Two strictly **read-only** REST adapters: a GitHub repository metadata reader and a Notion page metadata / bounded first-level block reader.
- Explicit allowlists for permitted GitHub repositories and Notion pages, with separate runtime environment credentials.
- Host-restricted HTTPS transport with disabled redirects, timeouts and response-size bounds.
- Three-step integration DAG (GitHub -> Notion -> provenance manifest); each read has a schema-pinned capability contract.
- Health snapshot covering 88 observed integrations, stored as **historical observations**, never executable grants.
- Additional tests for access controls, prompt-injection isolation, cached-output authorization and crash-after-start quarantine.
- CI workflow for Python 3.10, 3.12 and 3.13; see `docs/architecture.md` and `docs/repository-bootstrap.md`.

### Test and run

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
upaoi demo --db ./sandbox.sqlite
upaoi health --inventory data/plugin-health-2026-11-22.json
upaoi sources --fixture --repo NeuralBlitz/AgentOS \
  --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd \
  --db ./fixture-sources.sqlite
```

To attempt **live read-only API calls** after obtaining separate least-privilege credentials:

```bash
export UPAOI_GITHUB_TOKEN="..." # optional for public GitHub repositories
export UPAOI_NOTION_TOKEN="..." # mandatory for Notion REST
upaoi sources --repo NeuralBlitz/AgentOS \
  --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd \
  --db ./sources.sqlite --request-id demo-sources-001
```

The source adapter uses the official GitHub REST repository endpoint and the Notion page/children endpoints. It does **not** directly inherit ChatGPT plugin authentication. The `sources` command is an example, not a claim that a token has been supplied or that a live call was performed.

## What is NOT implemented

- No direct access to ChatGPT's connected plugin tokens from standalone Python. Separate GitHub/Notion REST read adapters exist, but an authenticated deployment gateway is still required.
- No LLM-based intent parsing or autonomous agent reasoning; the registry scores *provided* tags only.
- No job queue, distributed lock, concurrent execution, cancellation, secrets broker, interactive approval UI, multi-tenant RBAC, credential-scoped container sandbox, cost tracking, or production telemetry.
- The demo verifier checks an output *schema and content only*; it is not independent evidence for real-world claims.
- No automatic retry of failed steps with potential side effects. A failed write requires manual reconciliation before resuming.
- This is **not production ready**.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m nb_orchestrator.cli demo --db ./local-demo.sqlite
```

The demo performs a 3-step workflow using **local, fake adapters**: `read_text -> summarize -> verify`. Repeat the command with the same DB and request ID to observe checkpoint reuse (no adapter re-execution).

## Safety boundaries

P0 = read-only. P1 = internal writes. P2 = consequential external actions. P3 = destructive/admin/production operations. P1/P2/P3 are denied unless the caller **explicitly lists the approved capability ID**; they also require idempotency and a trusted post-write verifier. These are per-invocation approvals, *not a user approval service*.

This engine is intended to be called from an authenticated host after validating a trusted user approval token. Never derive `approvals` or `requested_grants` from untrusted retrieved documents or model outputs. Never expose the adapter dispatch method to arbitrary generated Python code.

### Important crash boundary

SQLite checkpoints protect *completed* steps. A crash after an external write but before its checkpoint may leave ambiguous state; the prototype does **not** automatically resolve this. Production support requires provider idempotency keys and a durable write-intent/outbox plus provider read-back reconciliation.

## Layout

- `src/nb_orchestrator/models.py` — contracts
- `src/nb_orchestrator/registry.py` — registry and routing
- `src/nb_orchestrator/engine.py` — plan validation and executor
- `src/nb_orchestrator/store.py` — durable state and event history
- `src/nb_orchestrator/cli.py` — local workflow demonstration
- `tests/test_engine.py` — security and reliability regression tests
- `docs/integration-plan.md` — next steps for plugin gateway and deployment

## Source control and review

The dedicated private repository is [`NeuralBlitz/UPAOI`](https://github.com/NeuralBlitz/UPAOI). The implementation is proposed on the `feat/bootstrap-upaoi-v0.2.0` development branch for review against `main`. **A branch or pull request is not a production deployment.** See `docs/repository-bootstrap.md` for setup and review procedures.

## Next engineering gates

1. Authenticated gateway for 2 read-only plugins (GitHub repository metadata + Notion source retrieval).
2. Formal policy decision point and independent authorization evidence; no user-input-only `approvals`.
3. Durable outbox and reconciliation protocol before any external writes.
4. Integration contract tests, negative security tests, and secrets management.
5. Host the runtime with persistent storage and queue, then add observability and controlled fallbacks.
