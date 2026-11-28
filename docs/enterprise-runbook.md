# UPAOI Enterprise Pilot — Operator Runbook (preproduction draft)

## Preconditions (not currently verified)

- A trusted identity provider issues RS256 JWT access tokens with validated issuer, fixed API audience, `sub`, `tenant_id`, `scope`, `jti`, and bounded `exp`/`iat`/`nbf`.
- Public JWKS is injected from a trusted deployment pipeline; private keys never enter application configuration. Document and test rollover.
- Dedicated scoped GitHub and Notion credentials are provisioned through a secrets manager; the ChatGPT-connected apps do not supply credentials to this Python process.
- A trusted HTTPS ingress enforces TLS, rate limits, request isolation, request limits and authenticated operator-only admin access.
- Dedicated persistent databases exist with filesystem ACLs, encryption-at-rest, backup/restore and audit-chain external anchoring. The current SQLite layer is not HA storage.

## Installation & local verification

```bash
python -m pip install -e '.[ci,enterprise-test]'
python -m unittest discover -s tests -v
python -m nb_orchestrator.cli agents --db :memory:
```

## Local test service

Follow [Enterprise pilot configuration](enterprise-pilot.md) and supply the required environment variables through a protected source. Run only on loopback for manual tests:

```bash
python -m uvicorn nb_orchestrator.enterprise_app:build_app_from_environment --factory --host 127.0.0.1 --port 8000
```

Only `/health/live` is unauthenticated. It says nothing about IdP readiness, database/credential health or actual workload readiness. Do **not** expose the sample app on `0.0.0.0` or publish it as enterprise-ready.

## Before any production candidacy

- Prove malformed/expired/wrong-issuer/wrong-audience/tampered JWTs are denied.
- Prove access control to the *exact GitHub repository and Notion page* using real provider credentials and read-back.
- Prove tenant-bound request IDs, scope revocation on replay, and denied high-risk capabilities.
- Confirm separate least-privilege identities for operators, services and agents.
- Stress-test SQLite contention before replacing it with a production-grade event store and fenced lease scheduler.
- Verify independent audit receipt storage, external chain anchoring, provider request traces and retention policy.
- Exercise restore-to-clean-environment, credential revocation, outage replay/quarantine, failed-provider fallback and rollback.
- Run an external security assessment and close critical/high vulnerabilities before enabling writes or inviting customers.

## Incident response basics

- **Suspected credential compromise:** revoke the upstream token/key, block ingress, preserve logs off-box, rotate secrets through change control; do not copy credentials into tickets or agent context.
- **Unexpected duplicate action:** disable any write-capable connector, quarantine the logical effect ID, inspect provider evidence and reconcile before retry. Writes are disabled in the v0.4 pilot.
- **Audit HMAC mismatch:** stop admission immediately, preserve database and signing key material separately, investigate, compare with independent anchors and backups. Never silently reset the log.
- **Stuck execution:** do not clear SQLite `claim_token` while the original worker might be running. Quiesce the old worker and follow an operator reconciliation procedure.
- **IdP outage / key rotation:** fail closed for admission. A liveness 200 is not operational readiness. Rotate public keys through reviewed configuration changes, not by trusting a JWT's `jku` header.

## Release evidence template

Record source commit/PR, CI run IDs and conclusions, dependency/scan results, observed load profile, IdP acceptance test records, tenant ACL results, signed approval for any high-risk action, audit-anchor verification, backup/restore drill results, known gaps and rollback instructions. Retain in the canonical Notion implementation ledger.

## Inspect existing audit receipts (offline)

Supply the same protected HMAC signing key used at event time and run:

```bash
python -m nb_orchestrator.cli audit-verify --audit-db /secure/path/gateway-audit.sqlite
```

The command rejects missing files or corrupted historic rows and prints the validated count and MAC tip. Back up and independently anchor that tip and sequence in a separate trust domain. **An unanchored deleted suffix cannot be detected by the local-only check.**


## v0.4.1 admission-ledger upgrade checklist

Before starting the environment factory, configure a **third distinct durable**
SQLite file with `UPAOI_ADMISSION_DB=/var/lib/upaoi/admission.sqlite`.
The variable is mandatory for this pilot; if unset or if it aliases the
execution/audit database, startup intentionally fails closed. Back up this
ledger and restrict its filesystem permissions under the service identity.

Optional policy ceilings are `UPAOI_TENANT_REQUESTS_PER_MIN=100` and
`UPAOI_PRINCIPAL_REQUESTS_PER_MIN=25`; a tenant limit must be at least the
principal limit. These values are prototype defaults, not production SLAs.
A 429 response includes a short `Retry-After`. A 409 is a request-ID collision or
a blocked execution and must not trigger an automatic write retry.

Use `upaoi audit-anchor --audit-db ...` to export a signed checkpoint and
**retain it externally**, away from the application host and audit key holder.
Use `upaoi audit-verify --audit-db ... --anchor-file ...` to detect deletion or
rollback of records predating that checkpoint. Do not claim the host is
independently anchored until that external storage and verification have
actually been configured and tested.

For ingress readiness, `GET /health/ready` tests local integrity and SQLite
health only. Continue to use the original runbook for TLS, secret management,
egress policy and independent IdP/provider integration smoke tests.
