# M3 live read-only source preflight — UPAOI v0.4.2

**Status:** optional implementation and synthetic CI smoke are available; the
live integration has not been exercised with real provider tokens, a hosted IdP
or production networking. Do not assume installed ChatGPT plugins expose their
runtime tokens to this standalone Python application.

## Admission boundary

1. Obtain a short-lived access JWT from an approved test IdP. It must be RS256
   signed, match the pinned issuer/audience, carry a trusted tenant claim and
   include `github:repository:read` and `notion:page:read` scopes. An IdP test
   token must be acquired through an authorized identity-provider flow.
2. Provision independent read-only GitHub and Notion test credentials with
   minimum access to **one** allowlisted repository and **one** Notion page.
   Supply all credentials through a protected, independently managed secret
   store. Do not commit credentials to GitHub, logs or example files.
3. Configure `UPAOI_ALLOWED_REPO`, `UPAOI_ALLOWED_NOTION_PAGE`,
   `UPAOI_OIDC_ISSUER`, `UPAOI_OIDC_AUDIENCE`, `UPAOI_OIDC_JWKS_JSON`,
   `UPAOI_TENANT_ID`, `UPAOI_OIDC_TEST_ACCESS_TOKEN`,
   `UPAOI_GITHUB_TOKEN`, and `UPAOI_NOTION_TOKEN`.
4. Execute `upaoi preflight` on an approved, isolated test host. The preflight
   never fetches or signs in automatically. It validates the access JWT first,
   rejects tenant/scope mismatch, then executes only read-only provider GETs.
5. The output is a minimal pass/fail *source reachability* receipt. It does not
   include the access token, page excerpt, repository metadata, or identifiable
   user subject. Its source-policy digest is deterministic and not a signature.
6. Independently check outbound egress, HTTP access logs (redacted), token
   expiry, key rotation and denial after revocation; archive approved evidence
   in a separate trust domain. These are **future operational gates**.

## Required negative tests before internal alpha

- Fail with missing credentials/issuer configuration without making requests.
- Reject bad signatures, wrong tenant, missing scopes and a changed audience.
- Deny any mismatched GitHub repository or Notion page.
- Confirm actual provider pages/repositories are limited by service credentials,
  not merely by code allowlists.
- Simulate outage/timeout/429 and verify that no raw API response or credential
  is written to a log or returned to a user.
- Verify provider reads against a clean test account and assess data retention.

**Gating decision:** M3 remains NOT APPROVED until real IdP and provider
integration evidence is captured, independently reviewed and a named operator
approves deployment controls.
