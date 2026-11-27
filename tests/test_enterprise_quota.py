"""Transactional quota limits: independent connections and privacy regression."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nb_orchestrator.enterprise_quota import AdmissionQuotaExceeded, QuotaLedger

T1 = 'a' * 64
T2 = 'b' * 64
P1 = 'c' * 64
P2 = 'd' * 64


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [180]
        self.path = Path(self.tmp.name) / 'quota.db'
        self.q = QuotaLedger(self.path, tenant_limit=4, principal_limit=2,
                             window_seconds=60, clock=lambda: self.now[0])

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_principal_limit_does_not_charge_other_dim_after_denial(self):
        self.q.reserve(tenant_digest=T1, principal_digest=P1)
        self.q.reserve(tenant_digest=T1, principal_digest=P1)
        with self.assertRaises(AdmissionQuotaExceeded) as caught:
            self.q.reserve(tenant_digest=T1, principal_digest=P1)
        self.assertEqual(caught.exception.retry_after_seconds, 60)
        self.q.reserve(tenant_digest=T1, principal_digest=P2)
        self.q.reserve(tenant_digest=T1, principal_digest=P2)
        with self.assertRaises(AdmissionQuotaExceeded):
            self.q.reserve(tenant_digest=T1, principal_digest=P2)
        self.assertEqual(sum(row[0] for row in self.q.connection.execute(
            "SELECT used FROM admission_quota WHERE dimension='principal'")), 4)

    def test_tenant_limit_is_shared_by_principals(self):
        for p in (P1, P2):
            for _ in range(2):
                self.q.reserve(tenant_digest=T1, principal_digest=p)
        with self.assertRaises(AdmissionQuotaExceeded):
            self.q.reserve(tenant_digest=T1, principal_digest='e' * 64)
        self.q.reserve(tenant_digest=T2, principal_digest='e' * 64)

    def test_window_rotation_frees_budget(self):
        for _ in range(2):
            self.q.reserve(tenant_digest=T1, principal_digest=P1)
        self.now[0] = 240
        self.q.reserve(tenant_digest=T1, principal_digest=P1)

    def test_denials_do_not_store_plaintext_identifiers(self):
        self.q.reserve(tenant_digest=T1, principal_digest=P1)
        rows = repr(self.q.connection.execute('SELECT * FROM admission_quota').fetchall())
        self.assertNotIn('alice', rows)
        self.assertNotIn('tenant-A', rows)

    def test_invalid_digests_and_budget_rejected(self):
        with self.assertRaises(ValueError):
            self.q.reserve(tenant_digest='tenant-A', principal_digest=P1)
        with self.assertRaises(ValueError):
            QuotaLedger(self.path, tenant_limit=2, principal_limit=5)

    def test_atomic_across_connections_and_threads(self):
        q2 = QuotaLedger(self.path, tenant_limit=4, principal_limit=2,
                         window_seconds=60, clock=lambda: self.now[0])
        try:
            def attempt(index):
                try:
                    (self.q if index % 2 == 0 else q2).reserve(
                        tenant_digest=T1, principal_digest=P1 if index < 12 else P2)
                    return True
                except AdmissionQuotaExceeded:
                    return False
            with ThreadPoolExecutor(max_workers=12) as pool:
                accepted = list(pool.map(attempt, range(24)))
            self.assertEqual(sum(accepted), 4)
            self.assertEqual(self.q.connection.execute(
                "SELECT used FROM admission_quota WHERE dimension='tenant'").fetchone()[0], 4)
        finally:
            q2.close()

    def test_closed_database_blocks_admission(self):
        self.q.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.q.reserve(tenant_digest=T1, principal_digest=P1)
