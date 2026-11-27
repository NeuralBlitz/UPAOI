# NeuralBlitz UPAOI — governed agent orchestration Enterprise Pilot Candidate v0.4.0

[![Test UPAOI](https://github.com/NeuralBlitz/UPAOI/actions/workflows/ci.yml/badge.svg)](https://github.com/NeuralBlitz/UPAOI/actions/workflows/ci.yml)

**UPAOI (Universal Plugin and Agent Orchestration Intelligence)** is a local, permission-aware Python workflow engine for constructing bounded, inspectable multi-agent flows. It currently supports deterministic local specialist handlers and strictly read-only GitHub/Notion REST adapter contracts.

**Status: enterprise read-only pilot candidate / NOT production-ready.** This is **not** a hosted autonomous agent platform, does **not** automatically inherit connected ChatGPT plugins, and does **not** dispatch to real LLM workers by default.

- [Canonical architecture blueprint](https://app.notion.com/p/41325ca447c181ac82aee167d8fe80fd)
- [GitHub repository](https://github.com/NeuralBlitz/UPAOI)
- [Integration limitations](docs/integration-plan.md)
- [Security and trust boundaries](docs/security.md)
- [Agent handoff contract](docs/agent-handoffs.md)

## v0.4 enterprise gateway (new, opt-in)

The optional REST gateway adds server-verified RS256 access tokens against operator-pinned public JWKS; tenant/workflow/capability/scope ACLs; authenticated namespaced request IDs; a strict read-only, server-registered workflow catalog; bounded JSON request envelopes; and HMAC-linked gateway audit receipts. It is **not deployed** and it does **not** inherit ChatGPT plugin credentials or enable autonomous external writes.

- [Enterprise gateway threat boundaries and setup](docs/enterprise-pilot.md)
- [Enterprise product milestone charter](docs/product-milestones.md)
- [Operator runbook and launch gates](docs/enterprise-runbook.md)
- [OIDC and service bootstrap module](src/nb_orchestrator/enterprise_app.py)

All live HTTP execution requires external IdP/public-key configuration, tenant/source allowlists, separate persistent state and audit stores, and separately provisioned GitHub and Notion credentials. Without these it refuses to start. **No live identity or provider end-to-end validation has been performed.**

## Implemented capabilities

- Version-pinned capability registry, risk classification, scopes, health checks and deterministic matching.
- Explicit agent capability allowlists intersected with per-workflow grants; unknown tools are denied by default.
- Dependency-validated DAG execution and structured references to completed step outputs (no `eval`).
- JSON Schema validation at input/output boundaries; errors sanitized before audit logging.
- SQLite checkpoints and event history, request/spec digest reuse, and quarantine of unfinished consequential operations.
- **v0.3:** Request IDs bound to a specified principal; completed results cannot be replayed under another principal, even if the caller knows their request ID.
- **v0.3:** Atomic SQLite execution claims prevent two local workers from invoking the same unfinished request at once. Claims have **no automatic expiration**: a process crash may require trusted operator investigation before replay.
- **v0.3:** Bounded, JSON-only specialist handoff packets with explicit objective, source references, data classification, acceptance criteria, immutable worker contracts and a separately registered reviewer.
- **v0.3:** Executable two-specialist local workflow (`analyst -> auditor`) with provenance and reviewer decisions. These workers are deterministic host callbacks, **not autonomous LLM agents**.
- Read-only, explicit allowlisted GitHub repository and Notion page REST adapters with scoped operator-provided credentials (not ChatGPT plugin credentials).
- CI test matrix covering Python 3.10, 3.12 and 3.13.

## Install and test

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ci,enterprise-test]"
python -m unittest discover -s tests -v
upaoi demo --db ./sandbox.sqlite
upaoi agents --db ./agents.sqlite --principal-id local-operator
upaoi health --inventory data/plugin-health-2026-11-22.json
```

`--principal-id` is a local **label**, not authentication. A future trusted gateway must derive principal identity from verified sessions, never from an untrusted request field.

Run a reproducible **synthetic** GitHub/Notion fixture without live network access:

```bash
upaoi sources --fixture \
  --repo NeuralBlitz/UPAOI \
  --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd \
  --db fixture.sqlite --request-id fixture-001
```

For separately provisioned read-only provider credentials, see `.env.example` and [the integration plan](docs/integration-plan.md). These integrations are **not** automatically authenticated by the connected ChatGPT GitHub or Notion applications.

## Agent handoffs

A trusted host registers an explicit specialist contract (agent ID, version, input/output schema, permitted source references and size quotas), a callable handler and a separate reviewer. The caller must supply a permitted specialist, permitted source references and permitted data classification. A valid source document **cannot grant itself new tools**, and a reviewer's acceptance **cannot authorize a write operation**.

Use `upaoi agents` to exercise the two-step pipeline and inspect accepted outputs. See [docs/agent-handoffs.md](docs/agent-handoffs.md) for the full contract and sample usage.

## Safety boundaries and limitations

- `P0` read operations have explicit grants and scope checks. `P1/P2/P3` operations additionally require approval IDs, idempotency and a trusted verifier, but these inputs are **not cryptographic approval receipts**. **Do not expose such operations in a public API.**
- `principal_id` is a trusted host assertion in the Python API, not an authentication system. A public web service must derive it from verified identity and enforce tenant isolation at all resource boundaries.
- Exclusive SQLite claims prevent concurrent attempts in the same shared database. They are not distributed fencing tokens or a queue; an abandoned claim is **not** automatically reset or stolen.
- Legacy pre-v0.3 request rows without a principal remain inaccessible until an operator performs a deliberate, audited migration; new databases are preferred for local demos.
- SQLite state is not encrypted, cryptographically immutable, or multi-tenant hardened. Treat local DB files as sensitive.
- Reviewers in the demo validate deterministic output contracts, not external factual truth or source credibility.
- No real specialist-model dispatch, durable queue, secure approvals, external-action outbox, multi-tenant RBAC, credential vault, hosted runtime, telemetry service, or production deployment exists yet.

## Development workflow

`main` contains the reviewed v0.2 bootstrap, while v0.3 is under review in PR #2. v0.4 should be developed as a stacked PR based on v0.3, and only retargeted to `main` after v0.3 merges. Improvements are proposed on new branches and verified through CI before merging. Do not merge into `main` or deploy production changes without explicit authorization.

## Repository layout

- `src/nb_orchestrator/engine.py`, `store.py`: policy, execution, principals, exclusive claims, checkpoints.
- `src/nb_orchestrator/agent_runtime.py`: bounded specialist contracts and dispatch.
- `src/nb_orchestrator/agent_workflow.py`: two-specialist local demonstration.
- `src/nb_orchestrator/providers.py`: read-only GitHub/Notion provider adapters.
- `tests/`: regression and security tests.
- `docs/`: architecture, integration, agent and security documentation.
