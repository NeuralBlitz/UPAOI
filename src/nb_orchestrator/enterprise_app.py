"""Opt-in, environment-configured read-only pilot application.

Import fails closed without identity-provider public keys, audit signing key,
explicit source allowlists and a tenant ID. Nothing auto-connects to ChatGPT.
Use TLS and rate limiting at a trusted ingress; do not bind this sample
publicly or enable write-capable adapters.
"""
from __future__ import annotations

import json
import os
import re

from .enterprise_audit import AuditJournal
from .enterprise_auth import OidcVerifier
from .enterprise_gateway import EnterpriseGateway, TenantPolicy
from .enterprise_http import create_app
from .integration_workflow import build_integration_engine
from .store import Store


def build_app_from_environment(environ: dict[str, str] | None = None):
    env = os.environ if environ is None else environ
    required = ("UPAOI_OIDC_ISSUER", "UPAOI_OIDC_AUDIENCE", "UPAOI_OIDC_JWKS_JSON",
                "UPAOI_AUDIT_KEY_HEX", "UPAOI_TENANT_ID", "UPAOI_ALLOWED_REPO",
                "UPAOI_ALLOWED_NOTION_PAGE", "UPAOI_EXECUTION_DB", "UPAOI_AUDIT_DB")
    if any(not env.get(name) for name in required):
        raise RuntimeError("UPAOI enterprise pilot requires complete trusted configuration")
    if (env["UPAOI_EXECUTION_DB"] == ":memory:" or env["UPAOI_AUDIT_DB"] == ":memory:"
            or env["UPAOI_EXECUTION_DB"] == env["UPAOI_AUDIT_DB"]):
        raise ValueError("pilot must use separate durable execution and audit databases")
    try:
        key = bytes.fromhex(env["UPAOI_AUDIT_KEY_HEX"])
        jwks = json.loads(env["UPAOI_OIDC_JWKS_JSON"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid trusted enterprise configuration") from exc
    tenant = env["UPAOI_TENANT_ID"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", tenant):
        raise ValueError("invalid configured tenant")
    verifier = OidcVerifier(issuer=env["UPAOI_OIDC_ISSUER"],
                            audience=env["UPAOI_OIDC_AUDIENCE"], jwks=jwks)
    audit = AuditJournal(env["UPAOI_AUDIT_DB"], signing_key=key)
    try:
        store = Store(env["UPAOI_EXECUTION_DB"])
        try:
            engine, workflow = build_integration_engine(
                store, allowed_repo=env["UPAOI_ALLOWED_REPO"],
                allowed_page=env["UPAOI_ALLOWED_NOTION_PAGE"],
            )
            required_caps = frozenset(step.capability_id for step in workflow.steps)
            tenant_scopes = frozenset({"github:repository:read", "notion:page:read"})
            gateway = EnterpriseGateway(
                engine=engine, verifier=verifier, audit=audit,
                catalog={"source-inventory": workflow},
                tenants={tenant: TenantPolicy(frozenset({"source-inventory"}),
                                               required_caps, tenant_scopes)},
            )
        except Exception:
            store.connection.close()
            raise
    except Exception:
        audit.close()
        raise
    return create_app(gateway)


# Launch with `uvicorn nb_orchestrator.enterprise_app:build_app_from_environment --factory`.
# Factory returns no app unless the entire trusted configuration is valid.
