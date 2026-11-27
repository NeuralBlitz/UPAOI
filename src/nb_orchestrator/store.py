"""SQLite execution ledger with principal binding and conservative exclusive claims.

A claim never expires automatically. After a process crash, a trusted operator
must explicitly reconcile the abandoned run before another worker may execute it.
This sacrifices automatic recovery to avoid concurrent external side effects.
"""
from __future__ import annotations

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


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RequestConflict(ValueError):
    """The same authenticated principal reused a request ID for different work."""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        # Safe within a multi-threaded ASGI worker only with method-level lock.
        self.connection = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS executions (
            request_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
            workflow_version TEXT NOT NULL, spec_digest TEXT NOT NULL,
            status TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL,
            principal_id TEXT, claim_token TEXT
        );
        CREATE TABLE IF NOT EXISTS step_results (
            request_id TEXT NOT NULL REFERENCES executions(request_id),
            step_id TEXT NOT NULL, result_json TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (request_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL REFERENCES executions(request_id),
            event_type TEXT NOT NULL, step_id TEXT, detail_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        # Additive migration. Pre-0.3 executions retain principal_id=NULL and are
        # deliberately inaccessible until an operator performs a trusted migration.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(executions)")}
        for column in ("principal_id", "claim_token"):
            if column not in columns:
                self.connection.execute(f"ALTER TABLE executions ADD COLUMN {column} TEXT")
        self.connection.commit()

    @synchronized
    def start(self, request_id: str, workflow_id: str, version: str, spec_digest: str,
              *, principal_id: str) -> None:
        if not isinstance(principal_id, str) or not principal_id.strip() or len(principal_id) > 200:
            raise ValueError("nonempty authenticated principal id required")
        # BEGIN IMMEDIATE serializes the first writer across SQLite connections.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT workflow_id,workflow_version,spec_digest,principal_id "
                "FROM executions WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing:
                if existing[3] != principal_id:
                    # Do not reveal whether the request exists or belongs to an old schema.
                    raise PermissionError("request id not accessible to this principal")
                if existing[:3] != (workflow_id, version, spec_digest):
                    raise RequestConflict("request ID is already bound to another workflow")
                return
            self.connection.execute(
                "INSERT INTO executions (request_id,workflow_id,workflow_version,spec_digest,"
                "status,reason,updated_at,principal_id,claim_token) VALUES (?,?,?,?,?,?,?,?,NULL)",
                (request_id, workflow_id, version, spec_digest, "RECEIVED", None, utcnow(), principal_id)
            )
            self._event(request_id, "RECEIVED", None, {"workflow_id": workflow_id, "version": version})

    @synchronized
    def claim(self, request_id: str, *, principal_id: str, token: str) -> bool:
        if not token:
            raise ValueError("empty claim token")
        with self.connection:
            cur = self.connection.execute(
                "UPDATE executions SET claim_token=? WHERE request_id=? AND principal_id=? "
                "AND claim_token IS NULL AND status != 'COMPLETED'",
                (token, request_id, principal_id),
            )
            return cur.rowcount == 1

    @synchronized
    def release(self, request_id: str, *, principal_id: str, token: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE executions SET claim_token=NULL WHERE request_id=? AND principal_id=? "
                "AND claim_token=?", (request_id, principal_id, token)
            )

    def _event(self, request_id: str, name: str, step_id: str | None, detail: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO events (request_id,event_type,step_id,detail_json,created_at) VALUES (?,?,?,?,?)",
                                (request_id,name,step_id,json.dumps(detail,sort_keys=True),utcnow()))

    @synchronized
    def emit(self, request_id: str, name: str, step_id: str | None = None, detail: dict | None = None) -> None:
        with self.connection:
            self._event(request_id,name,step_id,detail or {})

    @synchronized
    def status(self, request_id: str, status: str, reason: str | None = None) -> None:
        with self.connection:
            self.connection.execute("UPDATE executions SET status=?, reason=?, updated_at=? WHERE request_id=?",
                                    (status,reason,utcnow(),request_id))
            self._event(request_id,status,None,{"reason":reason})

    @synchronized
    def store_step(self, request_id: str, step_id: str, output: dict[str, Any], *, verification: str) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO step_results VALUES (?,?,?,?)",(request_id,step_id,json.dumps(output,sort_keys=True),utcnow()))
            self._event(request_id,"STEP_COMPLETED",step_id,{"verification":verification})

    @synchronized
    def outputs(self, request_id: str) -> dict[str, dict[str, Any]]:
        rows = self.connection.execute("SELECT step_id,result_json FROM step_results WHERE request_id=?",(request_id,)).fetchall()
        return {step_id: json.loads(raw) for step_id,raw in rows}

    @synchronized
    def state(self, request_id: str) -> tuple[str, str | None] | None:
        return self.connection.execute("SELECT status,reason FROM executions WHERE request_id=?",(request_id,)).fetchone()

    @synchronized
    def events(self, request_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT seq,event_type,step_id,detail_json,created_at FROM events WHERE request_id=? ORDER BY seq",(request_id,)).fetchall()
        return [dict(seq=seq,type=typ,step=step,details=json.loads(d),at=at) for seq,typ,step,d,at in rows]
