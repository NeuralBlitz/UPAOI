# NeuralBlitz UPAOI — governed agent orchestration Enterprise Pilot Candidate v0.4.1

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

`main` includes the merged v0.3 security and agent-handoff implementation ([PR #2](https://github.com/NeuralBlitz/UPAOI/pull/2)). The enterprise v0.4 gateway is proposed for review in [PR #3](https://github.com/NeuralBlitz/UPAOI/pull/3); it is not yet merged or deployed. Improvements are proposed on new branches and verified through CI before merging. Do not merge into `main` or deploy production changes without explicit authorization.

## Repository layout

- `src/nb_orchestrator/engine.py`, `store.py`: policy, execution, principals, exclusive claims, checkpoints.
- `src/nb_orchestrator/agent_runtime.py`: bounded specialist contracts and dispatch.
- `src/nb_orchestrator/agent_workflow.py`: two-specialist local demonstration.
- `src/nb_orchestrator/providers.py`: read-only GitHub/Notion provider adapters.
- `tests/`: regression and security tests.
- `docs/`: architecture, integration, agent and security documentation.


## Enterprise admission and externally anchored auditing (v0.4.1)

The opt-in enterprise gateway includes **fixed-window quotas enforced inside SQLite
transactions** for both the verified tenant and verified principal. A denied
request returns HTTP 429 with a bounded `Retry-After`, without invoking the
workflow. Every attempt, including a cached replay, consumes admission budget.
This protects internal-alpha execution capacity; it is **not** DDoS protection.
Use independent TLS ingress rate limits and a shared multi-node quota service
before a production launch.

For the environment-configured gateway, `UPAOI_ADMISSION_DB` is **required**
and must point to a distinct durable SQLite file. This intentional internal-alpha
configuration gate fails startup if the admission ledger is omitted.
Limits default to `UPAOI_TENANT_REQUESTS_PER_MIN=100` and
`UPAOI_PRINCIPAL_REQUESTS_PER_MIN=25`. These defaults must be benchmarked;
invalid settings fail startup. The app stores only hashed principal/tenant IDs
in the quota database.

`GET /health/ready` verifies the audit chain and local execution/admission
connections and returns 503 on failure; `/health/live` remains a minimal process
liveness endpoint. The asynchronous HTTP route delegates blocking execution to
a thread pool to keep the ASGI event loop responsive.

To export a signed checkpoint for an **independent, access-controlled store**:

```bash
UPAOI_AUDIT_KEY_HEX=... upaoi audit-anchor --audit-db /var/lib/upaoi/gateway-audit.db > anchor.json
UPAOI_AUDIT_KEY_HEX=... upaoi audit-verify --audit-db /var/lib/upaoi/gateway-audit.db --anchor-file anchor.json
```

The anchor is only useful against rollback when retained outside the host,
backed by an independently controlled retention policy, and protected from the
signing-key holder. See `docs/internal-alpha-gates.md`. No cloud anchor, IdP
registration or live external connector smoke test is included in this build.
