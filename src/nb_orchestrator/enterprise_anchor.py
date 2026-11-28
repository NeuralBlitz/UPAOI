"""Bounded reader for operator-retained external audit checkpoints.

A durable file visible to the service is only an external anchor when the
operator protects its write permissions and retention *outside* the service
host or a separate trust domain. This module cannot establish that property.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .enterprise_audit import AuditIntegrityError


class ExternalAnchorFile:
    """Read the independently held HMAC checkpoint without echoing its contents."""

    def __init__(self, path: str | Path, *, max_bytes: int = 4096):
        self.path = Path(path)
        if not self.path.is_absolute() or not 128 <= max_bytes <= 65536:
            raise ValueError("external audit anchor requires an absolute bounded path")
        self.max_bytes = max_bytes

    def __call__(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError("oversized anchor")
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("anchor must be an object")
            return parsed
        except (OSError, UnicodeError, ValueError, TypeError):
            # Filesystem paths, data and secrets must never appear in error text.
            raise AuditIntegrityError("external audit checkpoint unavailable or invalid") from None
