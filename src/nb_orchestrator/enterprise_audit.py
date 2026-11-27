"""HMAC-linked SQLite gateway-admission audit receipts.

This detects modifications to existing rows when the HMAC key is kept outside
SQLite. It is NOT an immutable or externally anchored audit log: deleting the
latest rows or a full rollback cannot be detected without independent anchoring.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class AuditIntegrityError(Exception):
    pass


class AuditJournal:
    def __init__(self, path: str | Path, *, signing_key: bytes):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("audit signing key must be at least 32 bytes and stored separately")
        self._key = signing_key
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS gateway_audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              run_ref TEXT NOT NULL,
              attributes TEXT NOT NULL,
              at TEXT NOT NULL,
              previous_mac TEXT NOT NULL,
              mac TEXT NOT NULL)
        """)

    @staticmethod
    def _encode(obj: dict[str, Any]) -> bytes:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    def _mac(self, payload: dict[str, Any]) -> str:
        return hmac.new(self._key, self._encode(payload), hashlib.sha256).hexdigest()

    @synchronized
    def append(self, event_type: str, run_ref: str, attributes: dict[str, Any]) -> int:
        if (event_type not in ("RUN_ADMITTED", "RUN_COMPLETED", "RUN_BLOCKED", "RUN_FAILED")
                or not isinstance(run_ref, str) or len(run_ref) != 64
                or not all(c in "0123456789abcdef" for c in run_ref)):
            raise ValueError("invalid audit event")
        # Do not accept arbitrary caller-supplied attributes or sensitive payloads.
        if set(attributes) - {"workflow_key", "status", "reason_code"}:
            raise ValueError("unexpected audit attribute")
        raw = self._encode(attributes)
        if len(raw) > 1024:
            raise ValueError("audit metadata exceeds size limit")
        stamp = datetime.now(timezone.utc).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            tail = self.connection.execute("SELECT seq,mac FROM gateway_audit ORDER BY seq DESC LIMIT 1").fetchone()
            seq, previous = ((tail[0] + 1), tail[1]) if tail else (1, "0" * 64)
            record = {"seq": seq, "event_type": event_type, "run_ref": run_ref,
                      "attributes": attributes, "at": stamp, "previous_mac": previous}
            mac = self._mac(record)
            self.connection.execute(
                "INSERT INTO gateway_audit(seq,event_type,run_ref,attributes,at,previous_mac,mac) "
                "VALUES (?,?,?,?,?,?,?)",
                (seq, event_type, run_ref, raw.decode("utf-8"), stamp, previous, mac),
            )
            self.connection.execute("COMMIT")
            return seq
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    @synchronized
    def verify(self) -> dict[str, Any]:
        previous, expected = "0" * 64, 1
        rows = self.connection.execute(
            "SELECT seq,event_type,run_ref,attributes,at,previous_mac,mac "
            "FROM gateway_audit ORDER BY seq"
        ).fetchall()
        for seq, event_type, run_ref, attributes, stamp, previous_mac, mac in rows:
            try:
                data = json.loads(attributes)
                record = {"seq": seq, "event_type": event_type, "run_ref": run_ref,
                          "attributes": data, "at": stamp, "previous_mac": previous_mac}
                valid = (seq == expected and hmac.compare_digest(previous_mac, previous)
                         and hmac.compare_digest(mac, self._mac(record)))
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise AuditIntegrityError(f"audit chain corrupted at sequence {seq}")
            expected += 1
            previous = mac
        return {"valid": True, "count": len(rows), "tip_mac": previous}

    @synchronized
    def close(self) -> None:
        self.connection.close()
