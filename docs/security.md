# UPAOI v0.3 threat model and security limitations

**Assets:** provider credentials, tenant-scoped task context, principal identity, audit history, SQLite execution results, approval evidence and agent outputs.

**Adversarial inputs:** crafted task envelopes, fake identities, forged provider responses, malicious source documents, output schema violations, duplicate IDs, crash windows and prompt injection.

| Threat | Current control | Remaining production gap |
| --- | --- | --- |
| Replay across principals | request IDs bound to `principal_id`; denies mismatch without outputs | trusted login and tenant ACLs; self-asserted CLI principal is not authentication |
| Unauthorized tool/agent | exact worker capability allowlists and requested grants | identity-bound grants from gateway |
| Cross-source leakage | exact allowlisted source refs and data classifications | tenant-level source authorization and redaction |
| Agent payload injection | JSON-only bounded context, schema validation, no `eval` | sandboxed real model/tool runtime and output policy |
| Reviewer self-approval | separately registered reviewer required | independent review model and attested provenance |
| Concurrent replay | SQLite atomic request claims | distributed leases with fencing and supervised recovery |
| Abandoned worker | claim persists, fail closed | operator-confirmed termination and auditable claim release |
| Schema-driven log leakage | generic validation error log, avoid raw secret values | encrypted audit sink and comprehensive redaction |
| Unknown GitHub/Notion source | exact allowlist before outgoing GET | vault, egress firewall and source ACL service |
| Unexpected redirects | fixed HTTPS hosts and redirects denied | network sandbox and DNS policy |
| Ambiguous external write | incomplete consequential steps quarantined | transactional outbox, provider receipts and reconciliation |
| SQLite tampering | application-level event append | tamper-evident external audit logs |

**Do not deploy the present `Engine` as a public execution endpoint.** The `approvals` argument is a set of caller-supplied capability IDs, not signed user consent, and `principal_id` is currently a trusted-host assertion rather than validated authentication. External write operations are not production safe.

**Migration note:** v0.3 adds principal and claim columns to existing `executions`. Old requests without a principal are deliberately inaccessible to all callers until safely migrated by an administrator. An abandoned claim must not be cleared while the old worker may still be alive.

## v0.4 enterprise gateway additions (development branch)

The optional ASGI pilot admission layer authenticates **RS256 JWTs against operator-pinned public JWKS**, enforces issuer/audience/exp/iat/nbf/jti checks and a short lifetime, derives principal identity from verified claims, intersects tenant policy with JWT scopes, and allows only pre-registered P0 workflows. Caller-supplied identity and approval values are rejected in its HTTP envelope. It is **not** an authorization system for P1/P2/P3 writes, and token revocation, IdP key discovery and rate limiting remain operational gaps.

A separate HMAC-linked SQLite gateway-admission journal detects modifications to retained rows with an uncompromised signing key, but **does not detect deleted suffixes, full database rollback or key theft** without independently anchored receipts. Neither this journal nor SQLite is a certified, immutable enterprise audit service.

`Store` and `AuditJournal` connections support ASGI worker threads with local per-connection locks; they do not provide multi-node fencing, distributed transactions, or production SLAs. See [enterprise pilot](enterprise-pilot.md), [runbook](enterprise-runbook.md) and [product milestones](product-milestones.md).
