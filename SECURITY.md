# Security policy — experimental MVP

This repository currently contains a local prototype and read-only provider adapters. It is **not a production service** and offers no security guarantees beyond the documented local regression tests.

Report a suspected vulnerability privately to the repository owner using GitHub's private vulnerability reporting if enabled; otherwise use a non-public channel. Do not post credentials, exploit payloads containing private data, or unredacted logs in a public issue.

Before production use, review `docs/security.md`; implement authenticated operator identity, scoped secrets, tenant isolation, approval attestations, execution leases, audit retention and durable external-write reconciliation. External write execution is not enabled in this MVP.
