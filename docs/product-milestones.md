# UPAOI Enterprise — Product Milestone Charter

**Product hypothesis (not yet customer-validated):** teams operating agents across research, engineering and knowledge tools need a governed control plane that supplies explicit permissions, evidence, retry/recovery semantics, and inspectable execution history instead of unrestricted agent loops.

**Initial product wedge:** authorized read-only *portfolio intelligence*: inspect allowlisted GitHub repositories and Notion project records, produce a versioned, verified source inventory, and retain a tenant-scoped execution record. Target persona: engineering manager / platform engineer / research operations lead. The current proof-of-concept records source references, **not independently verified factual conclusions**.

## Release gates

| Gate | Concrete deliverable | Acceptance / evidence | Status at v0.4.0 PR |
| --- | --- | --- | --- |
| M0 — Core research MVP | Typed DAG, explicit capability allowlists, 2-provider synthetic inventory | Repeatable local unit tests and read-only mocked adapters | **Implemented and locally verified** (v0.2) |
| M1 — Safe specialist prototype | Principal-bound request state, local exclusive claims, worker/reviewer contracts | Unit/concurrency/security tests; GitHub CI | **Merged into main on 2026-11-27**; prior CI verified |
| M2 — Enterprise gateway foundation | Pinned RS256/OIDC validation, strict tenant/capability gate, registered P0 workflows, bounded HTTP envelope, audit receipt chain | Local negative auth/ACL tests, HMAC integrity tests; CI matrix 3.10/3.12/3.13 | **Implemented in PR #3, CI verified (Python 3.10/3.12/3.13), not merged** |
| M3 — Controlled internal alpha | Live read-only provider calls with separately issued scoped service credentials; audit reconcilability; OIDC key rotation | Identity-provider smoke tests, real source allowlist, incident drill, centralized secrets, no unauthorized access | **NOT DONE** |
| M4 — Enterprise preproduction | PostgreSQL event store, ordered event journal, distributed fenced leases, transactional external-effect ledger, external audit anchoring, OTel, tenant isolation tests | Chaos/restart tests, backup/restore, distributed concurrency, penetration test, SAST/SCA, independent review | **NOT DONE** |
| M5 — Private product beta | Multi-user operator UI, approval UX, tenant/budget governance, agent runtime isolation, human-in-the-loop writes only behind reconciled approvals | Measured performance, retention policy, response procedures, security review, operator docs, 2+ controlled pilot users | **NOT DONE** |
| M6 — General availability decision | Explicit SLAs, customer contracts, DR, incident escalation, security documentation, support operation, compliance assessment | External release signoff and documented evidence for each gate | **NOT DONE** |

**No completion date, staff assignment, commercial pricing, or certification is implied.** A completed PR or unit-test suite is not evidence of a deployed enterprise service.

## Proposed measurable requirements (targets, not achieved metrics)

- **Tenant separation:** zero unauthorized cross-tenant output or capability invocations in the automated authorization suite and a commissioned independent adversarial review.
- **External effect correctness:** zero unreviewed write replays; every outbound write carries a unique logical effect key, scoped approval, immutable provider receipt when available, and read-back verification or an explicit UNKNOWN state.
- **Reliability:** candidate service availability target of 99.9% monthly once HA infrastructure exists; independent measurements and an agreed error-budget policy are prerequisites.
- **Latency:** propose p95 HTTP admission (excluding downstream provider work) below 250 ms under an agreed benchmark load, with per-provider/step deadlines and per-tenant budgets.
- **Audit:** every admitted run has a correlated terminal or explicitly unresolved record; external anchor of audit-chain tips; operator review of unmatched admissions.
- **Supply chain:** automated Python 3.10/3.12/3.13 regression matrix, dependency vulnerability policy, pinned release artifacts, restricted protected branches, and a reproducible provenance manifest.
- **Operations:** documented secret rollover, backup restore, worker retirement, rollback, safe cancellation and incident playbooks; every procedure exercised in staging before release.

## Enterprise packaging and UX (product discovery backlog)

1. **Operator console:** workflows, agent/capability directory, execution logs, approvals, outcomes, run history and provenance graph. Design must separate evidence, inferred claims and decisions.
2. **Security workspace:** tenant roles, scoped grants, credential lifecycle, data retention, high-risk action approver records and audit export.
3. **Builder experience:** versioned workflow designer, typed schemas, dry-run fixtures, test gates, PR-review integration and API documentation.
4. **Commercial discovery:** interview target pilot users and test the value of a read-only cross-system intelligence use case before proposing tiers, pricing or staffing.
5. **Customer integration:** documented connector permission scopes, data classifications, webhooks and compatibility policy; refuse unverified plugins or undocumented side-effect claims.

## Go / no-go for an actual production launch

**NO-GO until** identity verification is tested against a real IdP; tenant authorization and per-source ACLs have independent review; credentials are held in a vault; TLS/egress/rate limits are enforced; distributed durability/fencing and recovery have evidence; operational and security monitoring exists; backup/restore and incident playbooks have passed; and a named operator approves the release.

Source links: [UPAOI Architecture Blueprint](https://app.notion.com/p/41325ca447c181ac82aee167d8fe80fd), [UPAOI Recovery/Security ADRs](https://app.notion.com/p/41325ca447c1817b9a09e2682e4b7b46), [UPAOI repository](https://github.com/NeuralBlitz/UPAOI).

## Development tracking

- [PR #3 — v0.4 enterprise gateway](https://github.com/NeuralBlitz/UPAOI/pull/3); [first successful CI run](https://github.com/NeuralBlitz/UPAOI/actions/runs/46080900625)
- [Issue #4 — M3 live IdP/connector verification](https://github.com/NeuralBlitz/UPAOI/issues/4)
- [Issue #5 — M4 Postgres journal/fencing/effect reconciliation](https://github.com/NeuralBlitz/UPAOI/issues/5)
- [Issue #6 — M4 security/observability/release controls](https://github.com/NeuralBlitz/UPAOI/issues/6)
- [Issue #7 — M5 operator console/product validation](https://github.com/NeuralBlitz/UPAOI/issues/7)
