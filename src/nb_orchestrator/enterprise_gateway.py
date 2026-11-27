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

from .engine import Engine
from .enterprise_audit import AuditJournal
from .enterprise_auth import AuthenticationDenied, OidcVerifier
from .models import Workflow


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
                 max_steps: int = 16):
        if not (1 <= max_steps <= 64) or not catalog or not tenants:
            raise ValueError("enterprise gateway requires bounded workflows and tenant policies")
        # Refuse to start on a visibly corrupt local audit chain.
        audit.verify()
        self.engine, self.verifier, self.audit = engine, verifier, audit
        self.catalog, self.tenants, self.max_steps = catalog, tenants, max_steps
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
        # Host derives both identity and run namespace from a verified token.
        principal = hashlib.sha256(
            json.dumps([identity.issuer, identity.tenant_id, identity.subject],
                       separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        run_id = hashlib.sha256((principal + "\x1f" + client_request_id).encode()).hexdigest()
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
