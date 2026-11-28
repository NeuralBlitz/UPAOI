"""Fail-closed, tenant-scoped read-only execution admission boundary.

The gateway registers server-controlled workflow definitions. Clients cannot
submit a tool identifier, agent instruction, privilege scope, principal or
approval. Callers present asymmetric signed JWTs validated by OidcVerifier.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Any

from .engine import Engine
from .enterprise_audit import AuditJournal
from .enterprise_auth import AuthenticationDenied, OidcVerifier
from .models import Workflow
from .enterprise_quota import QuotaLedger, AdmissionQuotaExceeded


class AuthorizationDenied(Exception):
    pass


@dataclass(frozen=True)
class TenantPolicy:
    workflows: frozenset[str]
    capabilities: frozenset[str]
    scopes: frozenset[str]


class EnterpriseGateway:
    def __init__(self, *, engine: Engine, verifier: OidcVerifier, audit: AuditJournal,
                 catalog: dict[str, Workflow], tenants: dict[str, TenantPolicy],
                 max_steps: int = 16, quota: QuotaLedger | None = None,
                 audit_anchor_reader: Callable[[], dict[str, Any]] | None = None):
        if not (1 <= max_steps <= 64) or not catalog or not tenants:
            raise ValueError("enterprise gateway requires bounded workflows and tenant policies")
        # If configured, verify an independently retained HMAC checkpoint as well as
        # the local chain before starting. An empty replacement DB must not pass.
        if audit_anchor_reader is not None:
            audit.verify_anchor(audit_anchor_reader())
        else:
            audit.verify()
        self.engine, self.verifier, self.audit = engine, verifier, audit
        self.catalog, self.tenants, self.max_steps, self.quota = catalog, tenants, max_steps, quota
        self.audit_anchor_reader = audit_anchor_reader
        for key, workflow in catalog.items():
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,95}", key):
                raise ValueError("invalid server workflow key")
            ordered = engine.ordered(workflow)
            if len(ordered) > max_steps:
                raise ValueError("server workflow exceeds step budget")
            for step in ordered:
                if engine.registry.get(step.capability_id).risk != "P0":
                    raise ValueError("enterprise pilot rejects all write-capable workflows")

    def execute(self, *, token: str, workflow_key: str, client_request_id: str) -> dict:
        identity = self.verifier.verify(token)
        if not isinstance(workflow_key, str) or workflow_key not in self.catalog:
            raise AuthorizationDenied("workflow not authorized")
        if (not isinstance(client_request_id, str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", client_request_id)):
            raise AuthorizationDenied("invalid request identifier")
        policy = self.tenants.get(identity.tenant_id)
        if policy is None or workflow_key not in policy.workflows:
            raise AuthorizationDenied("workflow not authorized")
        workflow = self.catalog[workflow_key]
        grants = {step.capability_id for step in workflow.steps}
        if not grants.issubset(policy.capabilities):
            raise AuthorizationDenied("workflow capability not permitted")
        for step in workflow.steps:
            cap = self.engine.registry.get(step.capability_id)
            if cap.risk != "P0":
                raise AuthorizationDenied("external writes disabled")
            if not set(cap.scopes).issubset(policy.scopes & identity.scopes):
                raise AuthorizationDenied("read scope not permitted")
        # Re-read external checkpoint on each request. Fail closed before consuming
        # an admission quota or invoking a provider after rollback or tampering.
        self.check_audit_integrity()
        # Host derives both identity and run namespace from a verified token.
        principal = hashlib.sha256(
            json.dumps([identity.issuer, identity.tenant_id, identity.subject],
                       separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        run_id = hashlib.sha256((principal + "\x1f" + client_request_id).encode()).hexdigest()
        # Atomic request budget; derived identity, never a client-supplied tenant.
        if self.quota is not None:
            tenant_digest = hashlib.sha256(
                json.dumps([identity.issuer, identity.tenant_id], separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            try:
                self.quota.reserve(tenant_digest=tenant_digest, principal_digest=principal)
            except AdmissionQuotaExceeded:
                self.audit.append("RUN_RATE_LIMITED", run_id,
                                  {"workflow_key": workflow_key, "reason_code": "quota_exceeded"})
                raise
        # No raw principal, bearer, or workflow arguments in the gateway audit.
        self.audit.append("RUN_ADMITTED", run_id, {"workflow_key": workflow_key})
        try:
            result = self.engine.run(workflow, request_id=run_id, principal_id=principal,
                                     requested_grants=grants, approvals=set(),
                                     execution_scopes=policy.scopes & identity.scopes)
        except Exception:
            self.audit.append("RUN_FAILED", run_id,
                              {"workflow_key": workflow_key, "reason_code": "unexpected_engine_error"})
            raise
        status = result.status
        self.audit.append({"COMPLETED": "RUN_COMPLETED", "BLOCKED": "RUN_BLOCKED",
                           "FAILED": "RUN_FAILED"}[status], run_id,
                          {"workflow_key": workflow_key, "status": status})
        return {"request_id": client_request_id, "status": status,
                "outputs": result.outputs, "reason": result.reason}

    def check_audit_integrity(self) -> None:
        """Verify chain and operator-held checkpoint; never update the checkpoint here."""
        if self.audit_anchor_reader is not None:
            self.audit.verify_anchor(self.audit_anchor_reader())
        else:
            self.audit.verify()

    def check_ready(self) -> None:
        """Fail readiness when audit anchor, execution or admission ledger is down."""
        self.check_audit_integrity()
        self.engine.store.connection.execute("SELECT 1").fetchone()
        if self.quota is not None:
            self.quota.ping()
