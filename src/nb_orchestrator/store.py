"""Durable local execution state and append-only event records (SQLite)."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS executions (
            request_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
            workflow_version TEXT NOT NULL, spec_digest TEXT NOT NULL,
            status TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL
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
        self.connection.commit()

    def start(self, request_id: str, workflow_id: str, version: str, spec_digest: str) -> None:
        existing = self.connection.execute("SELECT workflow_id,workflow_version,spec_digest FROM executions WHERE request_id=?",(request_id,)).fetchone()
        if existing:
            if existing != (workflow_id, version, spec_digest):
                raise ValueError("request ID already belongs to a different workflow or spec")
            return
        with self.connection:
            self.connection.execute("INSERT INTO executions VALUES (?,?,?,?,?,?,?)",(request_id,workflow_id,version,spec_digest,"RECEIVED",None,utcnow()))
            self._event(request_id,"RECEIVED",None,{"workflow_id":workflow_id,"version":version})

    def _event(self, request_id: str, name: str, step_id: str | None, detail: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO events (request_id,event_type,step_id,detail_json,created_at) VALUES (?,?,?,?,?)",
                                (request_id,name,step_id,json.dumps(detail,sort_keys=True),utcnow()))

    def emit(self, request_id: str, name: str, step_id: str | None = None, detail: dict | None = None) -> None:
        with self.connection:
            self._event(request_id,name,step_id,detail or {})

    def status(self, request_id: str, status: str, reason: str | None = None) -> None:
        with self.connection:
            self.connection.execute("UPDATE executions SET status=?, reason=?, updated_at=? WHERE request_id=?",
                                    (status,reason,utcnow(),request_id))
            self._event(request_id,status,None,{"reason":reason})

    def store_step(self, request_id: str, step_id: str, output: dict[str, Any], *, verification: str) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO step_results VALUES (?,?,?,?)",(request_id,step_id,json.dumps(output,sort_keys=True),utcnow()))
            self._event(request_id,"STEP_COMPLETED",step_id,{"verification":verification})

    def outputs(self, request_id: str) -> dict[str, dict[str, Any]]:
        rows = self.connection.execute("SELECT step_id,result_json FROM step_results WHERE request_id=?",(request_id,)).fetchall()
        return {step_id: json.loads(raw) for step_id,raw in rows}

    def state(self, request_id: str) -> tuple[str, str | None] | None:
        return self.connection.execute("SELECT status,reason FROM executions WHERE request_id=?",(request_id,)).fetchone()

    def events(self, request_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT seq,event_type,step_id,detail_json,created_at FROM events WHERE request_id=? ORDER BY seq",(request_id,)).fetchall()
        return [dict(seq=seq,type=typ,step=step,details=json.loads(d),at=at) for seq,typ,step,d,at in rows]
