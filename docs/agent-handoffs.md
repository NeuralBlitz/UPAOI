# Typed specialist agent handoffs — v0.3.0

The specialist runtime is a **host-side registration boundary**: models, prompts, tool access and external credentials are not implicitly available to a worker. The demonstration uses Python callbacks, not LLMs.

## Inputs and contract

`SpecialistContract` defines the agent ID and immutable version, input/output JSON Schemas, explicit allowlisted source references, and maximum input/output sizes. `TaskPacket` supplies a bounded task ID, agent ID, version, objective, nonempty acceptance criteria, source references, JSON payload and data classification (`public`, `internal` or `restricted`).

`SpecialistRuntime.dispatch` requires three **host-supplied authorization sets**: `authorized_agents`, `authorized_sources`, and `allowed_classifications`. Documents, external web pages, LLM messages and specialist results must never populate these authorization sets.

## Acceptance and provenance

1. Reject unknown, unauthorized or mismatched agent IDs and versions.
2. Check classification and both source allowlists (contract and current invocation).
3. Limit serialized JSON payload size and validate input schema before invoking a worker.
4. Pass a detached JSON-only packet to the registered handler; no arbitrary code execution from payloads.
5. Check output size and JSON Schema. Reject unexpected capabilities/fields when the contract is closed.
6. Invoke a separately registered reviewer with a fresh detached payload and output snapshot. Fail closed if the reviewer rejects.
7. Return the worker ID, reviewer ID, contract version, exact context references, task ID and validated output.

## Working local example

```bash
python -m pip install -e .
upaoi agents --db agents.sqlite --principal-id local-operator
```

This runs a two-step DAG with `analyst` and `auditor` roles. Two separate registered reviewer callbacks verify their outputs. The workflow is deterministic, uses only fixture text, and makes **zero network, ChatGPT plugin or external LLM calls**. The reviewer demonstrates local contract consistency, not objective source truth.

## Security limitations

- Separately registered reviewer identity does **not** prove independence of the underlying human, model, or infrastructure.
- The host must authenticate a principal and enforce tenant/resource ACLs. A CLI-supplied ID is only a local test label.
- Data may be sensitive: redact and encrypt context, outputs, and SQLite checkpoints before hosting.
- A live agent executor must use sandboxing, rate limits, cancellation, logging, budget limits, credential isolation and per-call policy checks.
- The handoff API does not implement approvals for external writes. No model-generated instruction may become an `approvals` input or an authorization token.
- Future deployments must implement provenance validation, claim checks against primary evidence and adversarial prompt-injection evaluation.
