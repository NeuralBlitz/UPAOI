# M3.1 — Enterprise operational integrity hardening (v0.4.3)

**Status: implemented as an opt-in internal-alpha guard, not production certified.**
The user-visible goal is to stop read-only execution if a formerly trusted audit
history is rolled back and to prevent accidental SQLite database co-location.

## Trust contract

The existing `audit-anchor` command emits a signed `count`, `tip_mac`,
`anchor_mac` receipt. Store it **outside the UPAOI service's control** in an
append-only/immutable versioned destination under separate operator rights.
An operator may mount a verified, read-only checkpoint file for the pilot:

```text
UPAOI_REQUIRE_EXTERNAL_AUDIT_ANCHOR=1
UPAOI_EXTERNAL_AUDIT_ANCHOR_FILE=/run/secrets/upaoi-audit-anchor.json
```

The file **must exist before service startup**; the application never issues,
updates, or repairs it. On startup, each admitted request, and `/health/ready`,
the HMAC checkpoint is authenticated and compared against the local journal.
A missing, malformed, forged or stale-count-after-rollback checkpoint denies
admission. The HTTP endpoint returns a generic 503, never secrets or raw paths.
This is deliberately O(N) in audit events on each request and is suitable only
for a small pilot: a high-volume deployment needs bounded authenticated
checkpoints, cryptographically verifiable incremental state, and a separately
operated audit service.

### Important limitations

- A checkpoint only protects events **through its captured sequence**. An
  attacker may truncate events appended after the latest externally retained
  checkpoint without this mechanism detecting it.
- A local file controlled by the service is **not an independent anchor**, even
  though the file path is different. Operator-managed separation is required.
- If both the HMAC secret and protected external checkpoint are compromised,
  neither HMAC nor a local SQLite journal proves tamper resistance.
- Live, independent audit anchoring, key rotation and external restore drills
  **remain operational requirements**, not fulfilled by this code.
- A 503 means admission is halted. Do **not** automatically reissue anchors or
  reset the audit ledger to force service readiness.

## Storage isolation

The enterprise factory requires **three distinct absolute physical file paths**
for execution, audit and quota SQLite databases. It now rejects identical,
relative, normalized-aliased, symlinked, and existing hardlinked file paths
instead of only comparing raw string values. This provides defensive local
configuration validation, not a hosted database isolation guarantee.

## Acceptance evidence

Run:

```bash
python -m pip install -e '.[ci,enterprise-test]'
python -m unittest discover -s tests -v
python -m nb_orchestrator.cli preflight --fixture \
  --repo NeuralBlitz/UPAOI \
  --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd
```

The `test_enterprise_anchor.py` suite covers protected-anchor acceptance,
missing/tampered file denial, entire audit-log deletion, startup rejection,
HTTP 503 rejection, normalized paths, relative paths, hardlinks and symlinks.

**No go-live** until isolated provider identities, TLS ingress, security review,
operator-owned anchor storage, backup/restore and IdP lifecycle testing are
verified with production-like infrastructure.
