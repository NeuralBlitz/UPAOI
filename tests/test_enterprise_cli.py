"""CLI audit integrity verification respects configured key without leaking it."""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from nb_orchestrator.enterprise_audit import AuditJournal


class EnterpriseAuditCliTests(unittest.TestCase):
    def test_valid_chain_cli_and_missing_db(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "audit.db"
            key = b"Q"*32
            audit=AuditJournal(db,signing_key=key)
            audit.append("RUN_ADMITTED","1"*64,{"workflow_key":"known"})
            audit.close()
            run=subprocess.run([sys.executable,"-m","nb_orchestrator.cli","audit-verify","--audit-db",str(db)],
                               env={**os.environ,"UPAOI_AUDIT_KEY_HEX":key.hex()},
                               capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('"count": 1',run.stdout)
            self.assertNotIn(key.hex(),run.stdout)
            missing=subprocess.run([sys.executable,"-m","nb_orchestrator.cli","audit-verify","--audit-db",str(Path(root)/"missing.db")],
                                   env={**os.environ,"UPAOI_AUDIT_KEY_HEX":key.hex()},
                                   capture_output=True,text=True)
            self.assertNotEqual(missing.returncode,0)
            self.assertFalse((Path(root)/"missing.db").exists())

    def test_cli_rejects_wrong_key(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/"audit.db"
            a=AuditJournal(db,signing_key=b"A"*32)
            a.append("RUN_ADMITTED","2"*64,{"workflow_key":"known"})
            a.close()
            run=subprocess.run([sys.executable,"-m","nb_orchestrator.cli","audit-verify","--audit-db",str(db)],
                               env={**os.environ,"UPAOI_AUDIT_KEY_HEX":(b"B"*32).hex()},
                               capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn("integrity check failed",run.stderr)
