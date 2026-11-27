"""Non-executable health observations. A successful probe is not authorization."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATUSES = {"response_ok", "blocked", "not_tested"}


@dataclass(frozen=True)
class HealthObservation:
    provider: str
    status: str
    probe: str | None
    detail: str


@dataclass(frozen=True)
class HealthSnapshot:
    date: str
    entries: tuple[HealthObservation, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> "HealthSnapshot":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise ValueError("health snapshot must contain items")
        entries = []
        seen = set()
        for item in raw["items"]:
            name = item.get("plugin")
            status = item.get("status")
            if not isinstance(name, str) or not name or name in seen or status not in STATUSES:
                raise ValueError("duplicate or invalid health record")
            seen.add(name)
            entries.append(HealthObservation(name,status,item.get("test"),item.get("details", "")))
        if len(entries) != raw.get("summary", {}).get("exposed"):
            raise ValueError("health inventory count mismatch")
        return cls(str(raw.get("date", "unknown")), tuple(entries))

    def counts(self) -> dict[str, int]:
        return {s: sum(e.status == s for e in self.entries) for s in ("response_ok","blocked","not_tested")}

    def blocked(self) -> tuple[str, ...]:
        return tuple(e.provider for e in self.entries if e.status == "blocked")
