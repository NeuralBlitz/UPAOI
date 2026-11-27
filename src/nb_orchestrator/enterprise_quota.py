"""Transactional, tenant/principal-bound read-only request admission.

This is an SQLite internal-alpha admission budget, NOT a distributed rate
limiter or a defense against network flooding. Put independent limits at the
TLS ingress, and replace this ledger with a highly available store before HA.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class AdmissionQuotaExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("request quota exceeded")


class QuotaLedger:
    """Atomic two-dimensional fixed-window limits with no raw tenant IDs.

    Both counters are written in one SQLite transaction, ensuring denied
    requests do not consume the other dimension's budget. Quota is charged
    per API call, including a cached request replay.
    """

    def __init__(self, path: str | Path, *, tenant_limit: int = 100,
                 principal_limit: int = 25, window_seconds: int = 60,
                 clock: Callable[[], float] = time.time):
        if (not (1 <= principal_limit <= tenant_limit <= 100_000)
                or not (10 <= window_seconds <= 86_400)):
            raise ValueError("invalid admission budget")
        self.tenant_limit, self.principal_limit = tenant_limit, principal_limit
        self.window_seconds, self.clock = window_seconds, clock
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(path), timeout=10, isolation_level=None,
                                          check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS admission_quota (
              window_bucket INTEGER NOT NULL,
              dimension TEXT NOT NULL CHECK(dimension IN ('tenant','principal')),
              subject_digest TEXT NOT NULL,
              used INTEGER NOT NULL CHECK(used > 0),
              PRIMARY KEY(window_bucket,dimension,subject_digest))
        """)

    def reserve(self, *, tenant_digest: str, principal_digest: str) -> None:
        if not isinstance(tenant_digest, str) or not _DIGEST.fullmatch(tenant_digest):
            raise ValueError("invalid tenant digest")
        if not isinstance(principal_digest, str) or not _DIGEST.fullmatch(principal_digest):
            raise ValueError("invalid principal digest")
        now = int(self.clock())
        bucket = now // self.window_seconds
        retry_after = self.window_seconds - now % self.window_seconds
        dimensions = (("tenant", tenant_digest, self.tenant_limit),
                      ("principal", principal_digest, self.principal_limit))
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                # Reap only old buckets; no PII or credentials are stored here.
                self.connection.execute("DELETE FROM admission_quota WHERE window_bucket < ?",
                                        (bucket - 1,))
                for dimension, digest, limit in dimensions:
                    row = self.connection.execute(
                        "SELECT used FROM admission_quota "
                        "WHERE window_bucket=? AND dimension=? AND subject_digest=?",
                        (bucket, dimension, digest)).fetchone()
                    if row and row[0] >= limit:
                        self.connection.execute("COMMIT")
                        raise AdmissionQuotaExceeded(retry_after)
                for dimension, digest, _ in dimensions:
                    self.connection.execute(
                        "INSERT INTO admission_quota(window_bucket,dimension,subject_digest,used) "
                        "VALUES(?,?,?,1) ON CONFLICT(window_bucket,dimension,subject_digest) "
                        "DO UPDATE SET used=used+1", (bucket, dimension, digest))
                self.connection.execute("COMMIT")
            except AdmissionQuotaExceeded:
                raise
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def ping(self) -> None:
        with self._lock:
            self.connection.execute("SELECT 1").fetchone()

    def close(self) -> None:
        with self._lock:
            self.connection.close()
