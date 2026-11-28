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
from pathlib import Path

from .enterprise_anchor import ExternalAnchorFile

from .enterprise_audit import AuditJournal
from .enterprise_auth import OidcVerifier
from .enterprise_gateway import EnterpriseGateway, TenantPolicy
from .enterprise_quota import QuotaLedger
from .enterprise_http import create_app
from .integration_workflow import build_integration_engine
from .store import Store


def _validate_storage_paths(databases: list[str]) -> None:
    """Require three distinct, absolute, non-symlink paths for the alpha stores.

    A string inequality check can be defeated by path aliases and hardlinks;
    audit and execution separation must refer to distinct physical files.
    """
    paths = [Path(name) for name in databases]
    if (any(not name.is_absolute() or str(name) == ":memory:" or name.is_symlink()
            for name in paths)
            or len({str(name.resolve()) for name in paths}) != len(paths)):
        raise ValueError("pilot databases require distinct absolute physical paths")
    for i, left in enumerate(paths):
        for right in paths[i+1:]:
            if left.exists() and right.exists() and os.path.samefile(left, right):
                raise ValueError("pilot databases must not share the same physical file")


def build_app_from_environment(environ: dict[str, str] | None = None):
    env = os.environ if environ is None else environ
    required = ("UPAOI_OIDC_ISSUER", "UPAOI_OIDC_AUDIENCE", "UPAOI_OIDC_JWKS_JSON",
                "UPAOI_AUDIT_KEY_HEX", "UPAOI_TENANT_ID", "UPAOI_ALLOWED_REPO",
                "UPAOI_ALLOWED_NOTION_PAGE", "UPAOI_EXECUTION_DB", "UPAOI_AUDIT_DB",
                "UPAOI_ADMISSION_DB")
    if any(not env.get(name) for name in required):
        raise RuntimeError("UPAOI enterprise pilot requires complete trusted configuration")
    databases = [env["UPAOI_EXECUTION_DB"], env["UPAOI_AUDIT_DB"], env["UPAOI_ADMISSION_DB"]]
    _validate_storage_paths(databases)
    anchor_required = env.get("UPAOI_REQUIRE_EXTERNAL_AUDIT_ANCHOR", "0")
    if anchor_required not in ("0", "1"):
        raise ValueError("invalid audit anchor policy")
    anchor_path = env.get("UPAOI_EXTERNAL_AUDIT_ANCHOR_FILE", "")
    if anchor_required == "1" and not anchor_path:
        raise RuntimeError("independently retained audit checkpoint required")
    anchor_reader = ExternalAnchorFile(anchor_path) if anchor_path else None
    try:
        key = bytes.fromhex(env["UPAOI_AUDIT_KEY_HEX"])
        jwks = json.loads(env["UPAOI_OIDC_JWKS_JSON"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid trusted enterprise configuration") from exc
    tenant = env["UPAOI_TENANT_ID"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", tenant):
        raise ValueError("invalid configured tenant")
    try:
        tenant_limit = int(env.get("UPAOI_TENANT_REQUESTS_PER_MIN", "100"))
        principal_limit = int(env.get("UPAOI_PRINCIPAL_REQUESTS_PER_MIN", "25"))
    except ValueError as exc:
        raise ValueError("invalid configured admission budget") from exc
    verifier = OidcVerifier(issuer=env["UPAOI_OIDC_ISSUER"],
                            audience=env["UPAOI_OIDC_AUDIENCE"], jwks=jwks)
    audit = AuditJournal(env["UPAOI_AUDIT_DB"], signing_key=key)
    try:
        quota = QuotaLedger(env["UPAOI_ADMISSION_DB"], tenant_limit=tenant_limit,
                            principal_limit=principal_limit)
    except Exception:
        audit.close()
        raise
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
                quota=quota, audit_anchor_reader=anchor_reader,
            )
        except Exception:
            store.connection.close()
            raise
    except Exception:
        quota.close()
        audit.close()
        raise
    return create_app(gateway)


# Launch with `uvicorn nb_orchestrator.enterprise_app:build_app_from_environment --factory`.
# Factory returns no app unless the entire trusted configuration is valid.
