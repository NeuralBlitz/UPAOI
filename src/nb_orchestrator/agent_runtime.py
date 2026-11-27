"""Bounded, host-supplied specialist dispatch (no implicit LLM/tool execution).

A specialist is a trusted, registered Python callback. The runtime does not
infer grants from instructions, context, or the specialist's own output.
Reviewer callbacks provide application-level acceptance checks, *not*
permission to execute consequential external writes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator


class DispatchDenied(ValueError):
    """Reject a handoff before exposing a restricted context or invoking a worker."""


@dataclass(frozen=True)
class SpecialistContract:
    agent_id: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_sources: frozenset[str]
    max_payload_bytes: int = 16384
    max_output_bytes: int = 32768

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][\w.-]{0,63}", self.agent_id):
            raise ValueError("invalid agent identifier")
        if not self.version or self.max_payload_bytes <= 0 or self.max_output_bytes <= 0:
            raise ValueError("invalid specialist contract bounds")
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.output_schema)


@dataclass(frozen=True)
class TaskPacket:
    task_id: str
    agent_id: str
    version: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    context_refs: tuple[str, ...]
    payload: dict[str, Any]
    classification: str = "public"


SpecialistHandler = Callable[[TaskPacket], dict[str, Any]]
SpecialistReviewer = Callable[[TaskPacket, dict[str, Any]], bool]


class SpecialistRuntime:
    def __init__(self) -> None:
        self._contracts: dict[str, SpecialistContract] = {}
        self._handlers: dict[str, SpecialistHandler] = {}
        self._reviewers: dict[str, tuple[str, SpecialistReviewer]] = {}

    def register(self, contract: SpecialistContract, handler: SpecialistHandler, *,
                 reviewer_id: str, reviewer: SpecialistReviewer) -> None:
        if contract.agent_id in self._contracts:
            raise ValueError("duplicate specialist")
        if reviewer_id == contract.agent_id or not reviewer_id:
            raise ValueError("reviewer identity must differ from worker")
        self._contracts[contract.agent_id] = contract
        self._handlers[contract.agent_id] = handler
        self._reviewers[contract.agent_id] = (reviewer_id, reviewer)

    @staticmethod
    def _clone_json(value: Any, *, limit: int) -> Any:
        try:
            raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, OverflowError):
            raise DispatchDenied("handoff must contain ordinary JSON data") from None
        if len(raw.encode("utf-8")) > limit:
            raise DispatchDenied("handoff exceeds configured byte limit")
        return json.loads(raw)

    def dispatch(self, packet: TaskPacket, *, authorized_agents: set[str],
                 authorized_sources: set[str], allowed_classifications: set[str]) -> dict[str, Any]:
        if packet.agent_id not in authorized_agents or packet.agent_id not in self._contracts:
            raise DispatchDenied("specialist not authorized for request")
        contract = self._contracts[packet.agent_id]
        if contract.version != packet.version:
            raise DispatchDenied("specialist contract version mismatch")
        if not re.fullmatch(r"[A-Za-z0-9][\w.-]{0,127}", packet.task_id):
            raise DispatchDenied("invalid task ID")
        if (not isinstance(packet.objective, str) or not packet.objective.strip()
                or len(packet.objective.encode("utf-8")) > 4096
                or not packet.acceptance_criteria or len(packet.acceptance_criteria) > 16
                or any(not isinstance(x, str) or not x.strip() or len(x.encode("utf-8")) > 1024
                       for x in packet.acceptance_criteria)):
            raise DispatchDenied("objective and bounded acceptance criteria required")
        if (len(packet.context_refs) > 32
                or any(not isinstance(r, str) or len(r.encode("utf-8")) > 2048 for r in packet.context_refs)):
            raise DispatchDenied("source reference metadata exceeds configured limits")
        if packet.classification not in ("public", "internal", "restricted") or packet.classification not in allowed_classifications:
            raise DispatchDenied("context classification not authorized")
        if len(packet.context_refs) != len(set(packet.context_refs)) or not set(packet.context_refs).issubset(contract.allowed_sources & authorized_sources):
            raise DispatchDenied("source reference not explicitly authorized")
        # Data snapshots are detached so neither handler nor reviewer may mutate
        # the caller's object, stored packet, or each other's result.
        original_payload = self._clone_json(packet.payload, limit=contract.max_payload_bytes)
        Draft202012Validator(contract.input_schema).validate(original_payload)
        safe_packet = TaskPacket(packet.task_id, packet.agent_id, packet.version,
                                 packet.objective, packet.acceptance_criteria,
                                 packet.context_refs, original_payload,
                                 packet.classification)
        output = self._clone_json(self._handlers[packet.agent_id](safe_packet),
                                  limit=contract.max_output_bytes)
        Draft202012Validator(contract.output_schema).validate(output)
        reviewer_id, reviewer = self._reviewers[packet.agent_id]
        reviewer_packet = TaskPacket(safe_packet.task_id, safe_packet.agent_id, safe_packet.version,
                                     safe_packet.objective, safe_packet.acceptance_criteria,
                                     safe_packet.context_refs,
                                     self._clone_json(packet.payload, limit=contract.max_payload_bytes),
                                     safe_packet.classification)
        approved = reviewer(reviewer_packet, self._clone_json(output, limit=contract.max_output_bytes))
        if approved is not True:
            raise DispatchDenied("independent reviewer rejected specialist output")
        return {"task_id": packet.task_id, "agent_id": packet.agent_id,
                "agent_version": packet.version, "reviewer_id": reviewer_id,
                "review_status": "accepted_by_registered_reviewer",
                "source_refs": list(packet.context_refs), "output": output}
