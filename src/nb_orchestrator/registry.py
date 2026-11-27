"""Contract-aware capability catalog and deterministic candidate ranking."""
from __future__ import annotations
from .models import Capability


class Registry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.risk not in ("P0", "P1", "P2", "P3"):
            raise ValueError("invalid risk class")
        if not 0 <= capability.reliability <= 1:
            raise ValueError("reliability must be between 0 and 1")
        if capability.id in self._items:
            raise ValueError(f"duplicate capability: {capability.id}")
        self._items[capability.id] = capability

    def get(self, capability_id: str) -> Capability:
        if capability_id not in self._items:
            raise KeyError(f"unknown capability: {capability_id}")
        return self._items[capability_id]

    def suggest(self, tags: set[str], allowed: set[str], *, max_risk: str = "P0") -> list[Capability]:
        """Rank only admissible capabilities; ranking never grants permission."""
        risk_value = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        if max_risk not in risk_value:
            raise ValueError("invalid maximum risk")
        items = [c for c in self._items.values()
                 if c.healthy and c.id in allowed and risk_value[c.risk] <= risk_value[max_risk]
                 and bool(set(c.tags) & tags)]
        return sorted(items, key=lambda c: (-len(set(c.tags) & tags), -c.reliability, c.id))
