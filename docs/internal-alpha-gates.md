# Internal alpha admission and audit acceptance gates — UPAOI v0.4.1

**Status:** implemented locally and verified by automated tests; not deployed.
**Product use case:** authorized read-only portfolio intelligence across an
explicitly allowlisted GitHub repository and Notion page. A manifest is a
reference packet, not an independently verified factual research report.

## Implemented contracts

1. **Verified identity:** RS256 issuer/audience/tenant validation with public
   signing keys pinned by the operator; no auto-downloaded JWKs and no
   untrusted algorithm selection.
2. **Capability gate:** tenant-policy workflow/capability/scope intersections;
   P1/P2/P3 provider actions rejected.
3. **Admission quota:** uniform per-tenant and per-principal fixed-window
   counters in a third durable SQLite file, as an internal-alpha concurrency
   control. 429 with bounded `Retry-After`; no capability dispatch on denial.
4. **Transport:** bounded JSON request body, one bearer header, generic 401/403,
   409 for request collision, 429 for quota, and HMAC-audited outcomes.
5. **Audit:** HMAC-chained local append-only-by-application audit journal; local
   corruption detection, signed checkpoint export and verification against an
   **independently retained** checkpoint. Not immutable or independently anchored
   until an operator protects a copy elsewhere.
6. **Readiness:** 503 when local audit/SQLite checks fail. Does **not** verify
   external provider health or end-to-end credentials.

## Pending operational evidence — internal alpha NO-GO

- [ ] Confirm actual OIDC issuer/JWKS/claims/scopes in a segregated test tenant;
      validate signing-key rotation and revocation with a real IdP.
- [ ] Configure separate read-only GitHub and Notion credentials in a vault;
      prove the allowlisted source workflow end to end against provider APIs.
- [ ] Prove tenant isolation under deliberately swapped credentials and policy
      changes, with independent reviewer signoff.
- [ ] Configure TLS ingress, distributed denial-of-service controls, egress
      allowlist, logging redaction and bounded API timeouts; test deployments.
- [ ] Retain signed audit anchors in an external append-only destination under
      separate administrator rights and drill detection of truncation/rollback.
- [ ] Run data retention/privacy assessment and documented cleanup/restore.
- [ ] Run signed dependency inventory/SBOM and SCA; triage vulnerabilities.
- [ ] Perform penetration test and disaster/incident exercise, with named owner
      for the release decision.

## Product milestones

- **M2.1 implemented locally:** internal-alpha safety gates, request budgets,
  provider-response transport isolation, audit checkpoints and CI verification.
- **M3 pending:** authorized cloud IdP+provider integration, audit anchoring and
  operating playbooks tested against an actual deployment.
- **M4 pending:** durable PostgreSQL event journal, fenced work leases, provider
  receipt/effect reconciliation, telemetry and security evaluation.
- **M5 pending:** operator dashboard, customer pilot research, approvals and UX.

**Do not enable external writes, merge to main, or deploy** based only on the
automated success of this patch.

## v0.4.3 operational integrity layer

- [x] Optional externally retained signed audit anchor is enforced on startup, readiness and admission (automated unit tests).
- [x] Local SQLite path configuration rejects relative and physical aliases.
- [x] Audit rollback blocks HTTP execution with generic 503 and no adapter call.
- [ ] Validate the checkpoint is actually retained in a separately administered immutable store.
- [ ] Prove anchoring cadence, audit key rotation and restore drills in a real deployed environment.
