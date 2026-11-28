"""Fail-closed deterministic DAG execution with checkpoints and policy decisions."""
from __future__ import annotations
import hashlib
import json
import re
from uuid import uuid4
from dataclasses import asdict
from typing import Any
from jsonschema import Draft202012Validator, ValidationError, SchemaError
from .models import Adapter, Agent, Capability, ExecutionResult, Step, Verifier, Workflow
from .registry import Registry
from .store import Store, RequestConflict


class PolicyDenied(Exception):
    pass


class Engine:
    def __init__(self, registry: Registry, store: Store, agents: dict[str, Agent],
                 adapters: dict[str, Adapter], verifiers: dict[str, Verifier] | None = None) -> None:
        self.registry, self.store = registry, store
        self.agents, self.adapters, self.verifiers = agents, adapters, verifiers or {}

    @staticmethod
    def ordered(workflow: Workflow) -> list[Step]:
        by_id = {s.step_id: s for s in workflow.steps}
        if len(by_id) != len(workflow.steps):
            raise ValueError("duplicate step identifier")
        if not workflow.workflow_id or not workflow.version or not workflow.steps:
            raise ValueError("workflow must have identity, version, and steps")
        for step in workflow.steps:
            if not re.fullmatch(r"[a-zA-Z][\w-]{0,63}",step.step_id):
                raise ValueError("invalid step identifier")
            if step.step_id in step.depends_on or any(d not in by_id for d in step.depends_on):
                raise ValueError("invalid dependency")
        result, visited, visiting = [], set(), set()
        def visit(sid: str) -> None:
            if sid in visiting:
                raise ValueError("dependency cycle")
            if sid in visited:
                return
            visiting.add(sid)
            for dep in by_id[sid].depends_on:
                visit(dep)
            visiting.remove(sid)
            visited.add(sid)
            result.append(by_id[sid])
        for step in workflow.steps:
            visit(step.step_id)
        return result

    @staticmethod
    def _resolve(data: Any, outputs: dict[str, dict[str, Any]], deps: tuple[str, ...]) -> Any:
        # No eval or string interpolation. References must be to declared dependencies.
        if isinstance(data, dict) and set(data) == {"$ref"}:
            ref = data["$ref"]
            if not isinstance(ref,str):
                raise ValueError("reference must be string")
            parts = ref.split(".")
            if len(parts) < 2 or parts[0] not in deps or parts[0] not in outputs:
                raise ValueError("reference must target a completed dependency")
            value: Any = outputs[parts[0]]
            for part in parts[1:]:
                if not isinstance(value,dict) or part not in value:
                    raise ValueError(f"missing reference field: {ref}")
                value = value[part]
            return value
        if isinstance(data,dict):
            return {k:Engine._resolve(v,outputs,deps) for k,v in data.items()}
        if isinstance(data,list):
            return [Engine._resolve(v,outputs,deps) for v in data]
        return data

    def _check_policy(self, step: Step, capability: Capability, *, requested_grants: set[str],
                      approvals: set[str], execution_scopes: set[str]) -> None:
        if step.agent_id not in self.agents:
            raise PolicyDenied("unknown agent")
        if step.capability_id not in requested_grants or step.capability_id not in self.agents[step.agent_id].allowed_capabilities:
            raise PolicyDenied("capability not granted to agent and workflow")
        if not capability.healthy:
            raise PolicyDenied("provider is unavailable")
        if step.capability_version != capability.version:
            raise PolicyDenied("capability contract version drift")
        if not set(capability.scopes).issubset(execution_scopes):
            raise PolicyDenied("required connector scope missing")
        if capability.risk != "P0" and capability.id not in approvals:
            raise PolicyDenied(f"{capability.risk} action requires explicit capability approval")
        if capability.risk != "P0" and not capability.idempotent:
            raise PolicyDenied("non-idempotent write not safe for automatic execution")
        if capability.risk != "P0" and capability.id not in self.verifiers:
            raise PolicyDenied("write action needs trusted read-back verification")

    def run(self, workflow: Workflow, *, request_id: str, principal_id: str, requested_grants: set[str],
            approvals: set[str] | None = None, execution_scopes: set[str] | None = None) -> ExecutionResult:
        """Resume by request_id; completed steps are reused and never re-invoked."""
        if not request_id or len(request_id)>200:
            raise ValueError("invalid request id")
        ordered = self.ordered(workflow)
        canonical = json.dumps(asdict(workflow),sort_keys=True,ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        try:
            self.store.start(request_id, workflow.workflow_id, workflow.version, digest,
                             principal_id=principal_id)
        except PermissionError:
            # Neither the existence nor outputs of another principal's run leak.
            return ExecutionResult(request_id, "BLOCKED", {}, "request id not accessible")
        except RequestConflict:
            return ExecutionResult(request_id, "BLOCKED", {}, "request identifier conflicts with prior work")
        current = self.store.state(request_id)
        # Authorization is evaluated on *every* access, even cached reads.
        try:
            for step in ordered:
                capability = self.registry.get(step.capability_id)
                self._check_policy(step, capability, requested_grants=requested_grants,
                                   approvals=approvals or set(), execution_scopes=execution_scopes or set())
        except (PolicyDenied, KeyError) as exc:
            # A denied replay must not mutate the original execution's status.
            return ExecutionResult(request_id, "BLOCKED", {}, str(exc))
        if current and current[0] == "COMPLETED":
            return ExecutionResult(request_id, "COMPLETED", self.store.outputs(request_id))
        claim_token = uuid4().hex
        if not self.store.claim(request_id, principal_id=principal_id, token=claim_token):
            return ExecutionResult(request_id, "BLOCKED", {},
                                   "request already claimed; operator reconciliation required after a crash")
        try:
            outputs = self.store.outputs(request_id)
            # Crashes after STEP_STARTED on a non-P0 operation are ambiguous.
            events = self.store.events(request_id)
            started_writes = {e["step"] for e in events if e["type"] == "STEP_STARTED"
                              and e["details"].get("risk") != "P0"}
            if started_writes.difference(outputs):
                reason = "unfinished consequential step; manual reconciliation required"
                self.store.status(request_id, "BLOCKED", reason)
                return ExecutionResult(request_id, "BLOCKED", outputs, reason)
            self.store.status(request_id, "RUNNING")
            for step in ordered:
                if step.step_id in outputs:
                    continue
                try:
                    cap = self.registry.get(step.capability_id)
                    self._check_policy(step, cap, requested_grants=requested_grants,
                                       approvals=approvals or set(), execution_scopes=execution_scopes or set())
                    args = self._resolve(step.arguments, outputs, step.depends_on)
                    Draft202012Validator.check_schema(cap.input_schema)
                    Draft202012Validator.check_schema(cap.output_schema)
                    Draft202012Validator(cap.input_schema).validate(args)
                    if cap.id not in self.adapters:
                        raise PolicyDenied("adapter not registered")
                except (PolicyDenied, KeyError, ValueError, SchemaError, ValidationError) as exc:
                    # ValidationError.__str__ can contain entire sensitive input payloads.
                    reason = str(exc) if isinstance(exc, PolicyDenied) else f"step contract rejected: {type(exc).__name__}"
                    self.store.emit(request_id, "STEP_BLOCKED", step.step_id, {"reason": reason})
                    self.store.status(request_id, "BLOCKED", reason)
                    return ExecutionResult(request_id, "BLOCKED", outputs, reason)
                self.store.emit(request_id, "STEP_STARTED", step.step_id,
                                {"capability": cap.id, "version": cap.version, "risk": cap.risk,
                                 "agent": step.agent_id})
                try:
                    # Adapter execution occurs only after trusted host-bound grants.
                    result = self.adapters[cap.id](args)
                    Draft202012Validator(cap.output_schema).validate(result)
                    if cap.risk != "P0" and not self.verifiers[cap.id](args, result):
                        raise RuntimeError("trusted post-write read-back failed")
                    self.store.store_step(request_id, step.step_id, result,
                                          verification="schema" if cap.risk == "P0" else "schema+readback")
                    outputs[step.step_id] = result
                except Exception as exc:
                    self.store.emit(request_id, "STEP_FAILED", step.step_id,
                                    {"error_type": type(exc).__name__})
                    reason = f"step {step.step_id} failed; reconcile before retry: {type(exc).__name__}"
                    self.store.status(request_id, "FAILED", reason)
                    return ExecutionResult(request_id, "FAILED", outputs, reason)
            self.store.status(request_id, "COMPLETED")
            return ExecutionResult(request_id, "COMPLETED", outputs)
        finally:
            self.store.release(request_id, principal_id=principal_id, token=claim_token)
