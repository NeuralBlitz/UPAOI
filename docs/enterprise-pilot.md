# Enterprise read-only gateway — v0.4.0 (candidate)

> **Release class: integration / security pilot, not production GA.** These controls are implemented and locally tested, not penetration-tested, audited for compliance, deployed, or run against a real identity provider and live enterprise tenant.

## Intent and security model

The v0.4 gateway upgrades UPAOI from a local, caller-asserted `principal_id` to an authenticated, tenant-scoped admission boundary for **server-defined P0 read-only workflows**. It does **not** expose the v0.3 `Engine.run()` API directly to HTTP clients. No client can supply a `principal_id`, permissions, approvals, agent instructions, provider URLs, workflow steps, or write capability.

`Bearer JWT → pinned public JWKS/RS256 verification → tenant policy + JWT scope intersection → server-defined workflow → scoped Engine.run → HMAC-linked audit receipts → filtered JSON result`

### Implemented controls

1. **Signed identity:** RS256 only, pinned operator-supplied public JWKS (no network fetching), issuer/audience checked, required `iss`, `aud`, `sub`, `tenant_id`, `exp`, `iat`, `nbf`, `jti`, maximum token lifetime 15 minutes, maximum clock leeway 30 seconds. Unknown key IDs, invalid signature, malformed/expired/future JWTs and missing claims are rejected. Keys and issuer are never taken from request arguments.
2. **Tenant and resource access:** a tenant must be present in the server policy map. A workflow must be pre-registered by the operator. All its capability IDs must be permitted for that tenant, all required capability scopes must occur in both the tenant policy and the validated token, and every step must be P0. Per-provider resource readers still enforce exact GitHub repository and Notion page allowlists.
3. **Identity-safe idempotency:** execution IDs are SHA-256 derived from verified issuer, subject, tenant and the caller's bounded request ID. Reuse by another tenant/subject is namespaced independently. Cached results require fresh authentication and authorization on every attempt.
4. **HTTP admission:** only `POST /v1/runs` accepts `{"workflow_key":"source-inventory", "request_id":"..."}`; exactly two fields and JSON content type are required. Size budget: 4 KiB default, capped to 64 KiB by configuration. Duplicate Authorization headers are rejected; no docs/OpenAPI routes are served; `Cache-Control: no-store` is applied. Health endpoint `/health/live` only reports process liveness, **not** business readiness or production certification.
5. **Audit:** a separate SQLite journal records admission and terminal result event names with a keyed SHA-256 HMAC chain. No tokens, raw identity, provider data or arguments appear in those receipts. An existing chain is validated at gateway construction. Signing key must be protected separately from the database. No externally anchored tip exists yet, so suffix deletion/database rollback remain undetectable.
6. **SQLite threading:** local Store and audit calls are synchronized within one application process, and SQLite write transactions serialize across processes that share the same database. This is **not** multi-node distributed fencing or a validated HA deployment.
7. **Fail closed:** app factory refuses missing JWKS, tenant, allowlists, signing key, or separate durable DB paths. It does not silently start anonymous or write-enabled execution.

### Request example

```http
POST /v1/runs
Content-Type: application/json
Authorization: Bearer <externally issued RS256 JWT>

{"workflow_key":"source-inventory", "request_id":"inventory-001"}
```

- `200`: workflow completed under the authenticated principal.
- `400`: invalid request envelope.
- `401`: invalid or missing verified identity.
- `403`: denied workflow, tenant, resource grant or token scope.
- `409`: runtime blocked / requires reconciliation (the JSON output describes the reason).
- `413`: request body exceeds policy limit.
- `424`: runtime execution failed; external/read-only errors need investigation.
- `5xx`: internal infrastructure failure; inspect sanitized server logs, reconcile unmatched audit admissions.

### Controlled local startup (not a production deployment)

```bash
python -m pip install -e '.[ci,enterprise]'
# Supply ALL required configuration through a secret store or protected local environment:
# UPAOI_OIDC_ISSUER, UPAOI_OIDC_AUDIENCE, UPAOI_OIDC_JWKS_JSON (public only),
# UPAOI_AUDIT_KEY_HEX (random secret, >=32 bytes), UPAOI_TENANT_ID,
# UPAOI_ALLOWED_REPO, UPAOI_ALLOWED_NOTION_PAGE, UPAOI_EXECUTION_DB, UPAOI_AUDIT_DB
# For the GitHub and Notion source inventory adapters, also supply separately scoped
# UPAOI_GITHUB_TOKEN and UPAOI_NOTION_TOKEN. They are NOT ChatGPT plugin credentials.
python -m uvicorn nb_orchestrator.enterprise_app:build_app_from_environment --factory \
  --host 127.0.0.1 --port 8000
```

The app **must not be exposed directly to the Internet**: attach a verified identity-provider key rotation process, TLS gateway, rate limiting, threat logging, IP/egress controls, backup/restore drills, and controlled release pipeline first.

### Configuration limitations

- JWKS is supplied by an operator and not discovered/rotated automatically. Validate new public keys out-of-band; coordinate rollovers with overlapping key IDs and validity windows.
- No session revocation or JTI deny-list exists. Short token lifetime reduces but does not eliminate credential replay exposure; require TLS and identity-provider revocation handling at the ingress.
- No user-managed tenant registration, organization directory mapping, dynamic authorization service, per-tenant encryption, retention policy, or legal compliance certification.
- No queue, worker fencing, distributed capacity management, runtime billing or admission rate limits inside this code. External ingress controls and a durable worker service are mandatory before broad deployment.
- A trusted provider may sign a token carrying a tenant claim; **the identity-provider tenant-claim issuance policy must be audited**, not assumed trustworthy solely because the signature verifies.
- A gateway audit chain is tamper-*evident* only under an uncompromised signing key and retained historic rows; it is **not immutable**, and unanchored suffix deletion cannot be detected. Back up/anchor outside the same trust boundary before enterprise use.
- Audit tracks admission/result only; the v0.3 event ledger remains a mutable application append history. Full transactional event sourcing and external receipts are pending.

### Evidence

Local tests exercise token validation, issuer/audience/expiry/scope checks, subject/tenant isolation, write prohibition, malformed payloads, duplicate Authorization headers, audit tampering, concurrent SQLite access and fail-closed configuration. GitHub-hosted CI results must be confirmed from the feature branch before merge.

Authoritative references: [PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html), [OWASP API1: Broken Object Level Authorization](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/).

### Operator audit verification

`upaoi audit-verify --audit-db /secure/path/gateway-audit.sqlite` validates the existing HMAC-linked journal with the separately injected `UPAOI_AUDIT_KEY_HEX` secret (never pass the key as a command-line argument). The command fails if the audit file is missing or the key does not match retained rows.
