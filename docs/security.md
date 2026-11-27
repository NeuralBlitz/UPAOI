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
