"""Versioned core contracts. No connector-specific credentials live here."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Risk = Literal["P0", "P1", "P2", "P3"]


@dataclass(frozen=True)
class Capability:
    provider: str
    action: str
    version: str
    tags: tuple[str, ...]
    risk: Risk
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    scopes: tuple[str, ...] = ()
    healthy: bool = True
    idempotent: bool = True
    reliability: float = 1.0

    @property
    def id(self) -> str:
        return f"{self.provider}.{self.action}"


@dataclass(frozen=True)
class Agent:
    agent_id: str
    allowed_capabilities: frozenset[str]
    # An agent's grants are an upper bound; requested workflow grants can only reduce them.


@dataclass(frozen=True)
class Step:
    step_id: str
    capability_id: str
    capability_version: str
    agent_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    version: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    status: Literal["COMPLETED", "BLOCKED", "FAILED"]
    outputs: dict[str, dict[str, Any]]
    reason: str | None = None


# Host-bound callable. Live ChatGPT plugins require a separate, trusted gateway.
Adapter = Callable[[dict[str, Any]], dict[str, Any]]
Verifier = Callable[[dict[str, Any], dict[str, Any]], bool]
