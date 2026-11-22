# UPAOI workflow playbooks v0.2

## WF-001: Read-only source inventory (implemented, fixture-tested)

**Input:** trusted `request_id`, exact GitHub repository and Notion page UUID from an authorized requester.

1. Supervisor grants only `github.repository_read`, `notion.page_read`, and `local.evidence_manifest` to the selected agents.
2. Collector queries a single allowlisted GitHub repository and projects its identity, branch, visibility and archive status.
3. Collector reads the requested Notion page metadata and a bounded first page of child blocks. `truncated` records partial retrieval.
4. Verifier creates an evidence manifest containing the two source URLs. This verifies *presence of references*, **not factual agreement or claim truth**.
5. Executor writes output checkpoints and structured events to SQLite; replay retains completed read results but first rechecks the current grants and scopes.

**Acceptance:** authorized source IDs succeed; unapproved resource IDs are denied before network; malicious provider data does not extend grants; schema violation fails closed; output keeps provenance.

**Execution modes:**

- `upaoi sources --fixture --repo NeuralBlitz/AgentOS --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd --db fixture.sqlite` (offline, synthetic data).
- `upaoi sources --repo NeuralBlitz/AgentOS --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd --db sources.sqlite` (live REST only after separate Notion token, with specific page access; not tested with live credentials).

## WF-002: Multi-agent research synthesis (planned)

Source discovery -> source triage -> independent second-source cross-check -> claim-level provenance ledger -> adversarial critique -> verified report. Reject unsupported claims and retain contradictions as explicit issues. SciSpace, Synapse and Parallel would each need their own authenticated adapters and contractual test coverage before live use.

## WF-003: Reviewable software delivery (planned)

Source inventory -> scoped issue -> branch -> patch -> static analysis/tests -> independent review -> PR -> human merge approval -> deploy gate. GitHub write operations are **not enabled in v0.2**. Never treat repository metadata scope as authorization to create a branch or merge changes.

## WF-004: Capability health audit (partially implemented)

`upaoi health --inventory data/plugin-health-2026-11-22.json` imports the historical status of 88 available plugin namespaces (73 successful sampled probes, 5 blocked, 10 not safely tested). It cannot invoke any of those plugin tools or assume their future availability. A future trusted host can refresh a signed health snapshot with a TTL and per-action status.

## WF-005: Governance and approvals (planned)

Policy decision -> signed approval challenge -> specific capability and resource lease -> execution -> provider read-back -> audit receipt -> expiry/revocation. User/model strings like `approvals={...}` are not sufficient authentication in a public service.
