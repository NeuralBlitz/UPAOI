# Threat model & operational guardrails (prototype)

**Assets:** access tokens, Notion data, repository metadata, workflow approvals, SQLite execution state and audit trail.

**Adversarial inputs:** caller arguments, malicious source document text, forged provider results, token exposure in exception messages, duplicate request IDs, crash windows, redirection and unauthorized resource identifiers.

| Threat | Current protection | Production gap |
| --- | --- | --- |
| Unknown repository/page access | fixed allowlist checked before network | tenant-bound policy enforcement service |
| SSRF or unexpected redirect | fixed hosts, adapter-controlled paths, redirects rejected | egress firewall / DNS rebinding policy |
| Credential disclosure | secrets loaded from env, responses projected, errors sanitized | vault and secrets redaction pipeline |
| Prompt injection via documents | source content kept as data, not executable grants | isolated LLM planner + semantic guardrails |
| Schema drift | strict JSON Schema and pinned capability contract | provider version migration policy |
| Replay leakage | policy re-checked before cached outputs are returned | user-bound access to checkpoint records |
| Ambiguous external write | interrupted or failed non-P0 steps quarantined | durable outbox, provider receipts, reconciliation |
| Concurrent same-request execution | **not protected** | atomic distributed lease + fencing tokens |
| SQLite modification | application append-only events | externally tamper-evident audit sink |

**Never** accept a caller-supplied approval list in a public API. The trusted host must derive approvals from authenticated, signed evidence and apply least-privilege capabilities.
