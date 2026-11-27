# Live connector gateway plan (proposed; not implemented)

**v0.3 checkpoint:** Principal-bound local requests, SQLite exclusive claims and
JSON-only specialist handoff callbacks have been implemented and tested.
The host authentication gateway, live LLM dispatch, external approval receipts,
and production provider integration are still not implemented.


## 1. Trust boundaries

- `Intent API`: receives authenticated user request and data classification.
- `Policy service`: verifies identity, consent, workspace authorization, and allowed capabilities. Records signed scoped approval grants, never inferred from text.
- `Adapter gateway`: exposes only explicitly allowlisted connector operations with pinned input/output schemas. It runs under scoped, server-managed credentials and never exposes credentials to workers.
- `Workflow engine`: receives a versioned DAG and a signed, time-limited capability lease. Cannot elevate its own rights.
- `Audit`: records immutable reference metadata, redacted inputs and output digests, not raw secrets.

## 2. First two live adapters (read-only)

| Canonical ID | Initial action | Risk | Verification | Blocker |
| --- | --- | --- | --- | --- |
| github.repository.read | GitHub connector `get_repo` | P0 | Compare returned repository ID and owner to expected; validate schema | Host-to-plugin gateway API unavailable in standalone Python |
| notion.page.read | Notion connector `fetch` | P0 | Exact page ID + content digest; source URL and timestamp | Host-to-plugin gateway API unavailable in standalone Python |

Do not pretend ChatGPT chat-session plugins are automatically importable by a separate daemon or Docker runtime. The gateway needs an actual supported connector API or independent OAuth integrations.

## 3. Candidate multi-agent workflow

`researcher` -> `analyst` -> `engineer` -> `verifier` -> `human reviewer`.

Every handoff uses: task ID, source refs, allowed capability IDs, schema version, deadline, output contract, acceptance criteria, and trace ID. The independent verifier checks both artifact content and recorded external receipts.

## 4. Deployment requirements

- Service identity + scoped secrets in managed secret store.
- Postgres for execution state, durable events, transactional outbox; queue with explicit concurrency limits.
- Health probes and connector failure circuit breakers.
- Request limits, bounded retries only for demonstrably idempotent operations.
- HTTP API auth and policy checks at *every* invocation.
- Strong isolation for untrusted model-generated text; never evaluate code from tool responses.
- Positive and negative tests: denial, drift, duplicate, crash at write boundary, timeout, cancel, data exfiltration, permission escalation, verifier failure.

## 5. Initial acceptance criteria

1. One read-only workflow uses both live adapters against known authorized sources.
2. Every invocation has an authenticated requester, scoped grant, and provenance.
3. A missing/expired grant denies without any plugin call.
4. A schema change or inaccessible source blocks safely and logs a visible error.
5. A simulated worker restart resumes without repeating completed read steps.
6. Audit entries can be inspected independently of agent messages.

## 6. Notion record relationships

Canonical architecture: https://app.notion.com/p/41325ca447c181ac82aee167d8fe80fd
Universal operating protocol: https://app.notion.com/p/41325ca447c1813f918afd57db294070

Source repository: https://github.com/NeuralBlitz/UPAOI
Existing v0.2 implementation record: https://app.notion.com/p/42025ca447c181fd9f81d42944be1600
Future milestones should be recorded under the existing UPAOI blueprint with exact PR, commit and CI links.
