"""Principal ownership, cross-process claims, and legacy-record security tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import asdict
from pathlib import Path

from nb_orchestrator import Agent, Capability, Engine, Registry, Step, Store, Workflow

SCHEMA_IN={"type":"object","required":["text"],"additionalProperties":False,
           "properties":{"text":{"type":"string"}}}
SCHEMA_OUT={"type":"object","required":["text"],"additionalProperties":False,
            "properties":{"text":{"type":"string"}}}


def setup_engine(store, adapter):
    reg=Registry()
    reg.register(Capability("local","read","1",("read",),"P0",SCHEMA_IN,SCHEMA_OUT))
    w=Workflow("w","1",(Step("one","local.read","1","worker",{"text":"secret"}),))
    engine=Engine(reg,store,{"worker":Agent("worker",frozenset({"local.read"}))},{"local.read":adapter})
    return engine,w


class ExecutionSecurityTests(unittest.TestCase):
    def test_cross_principal_replay_blocked_with_no_leak(self):
        store=Store()
        engine,workflow=setup_engine(store,lambda args:args)
        authorized=engine.run(workflow,request_id="shared-id",principal_id="user-alice",requested_grants={"local.read"})
        self.assertEqual(authorized.status,"COMPLETED")
        rejected=engine.run(workflow,request_id="shared-id",principal_id="user-bob",requested_grants={"local.read"})
        self.assertEqual(rejected.status,"BLOCKED")
        self.assertEqual(rejected.outputs,{})
        self.assertEqual(engine.run(workflow,request_id="shared-id",principal_id="user-alice",
                                    requested_grants={"local.read"}).status,"COMPLETED")
        store.connection.close()

    def test_denied_replay_does_not_change_original_status(self):
        store=Store()
        engine,workflow=setup_engine(store,lambda args:args)
        engine.run(workflow,request_id="one",principal_id="alice",requested_grants={"local.read"})
        n=len(store.events("one"))
        denial=engine.run(workflow,request_id="one",principal_id="alice",requested_grants=set())
        self.assertEqual(denial.status,"BLOCKED")
        self.assertEqual(store.state("one")[0],"COMPLETED")
        self.assertEqual(n,len(store.events("one")))
        store.connection.close()

    def test_exclusive_claim_prevents_second_worker_execution(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/"runs.sqlite")
            started=threading.Event()
            proceed=threading.Event()
            results=[]
            def slow(args):
                started.set()
                if not proceed.wait(5):
                    raise RuntimeError("test worker timeout")
                return args
            def first():
                st=Store(db)
                try:
                    engine,workflow=setup_engine(st,slow)
                    results.append(engine.run(workflow,request_id="collision",principal_id="user",
                                              requested_grants={"local.read"}))
                finally:
                    st.connection.close()
            th=threading.Thread(target=first)
            th.start()
            try:
                self.assertTrue(started.wait(3),"first worker never started")
                with_store=Store(db)
                try:
                    other,flow=setup_engine(with_store,lambda _:self.fail("second adapter invoked"))
                    second=other.run(flow,request_id="collision",principal_id="user",
                                     requested_grants={"local.read"})
                    self.assertEqual(second.status,"BLOCKED")
                    self.assertEqual(second.outputs,{})
                    self.assertIn("claimed",second.reason)
                finally:
                    with_store.connection.close()
            finally:
                proceed.set()
                th.join(timeout=6)
            self.assertFalse(th.is_alive())
            self.assertEqual(results[0].status,"COMPLETED")

    def test_abandoned_claim_requires_explicit_operator_recovery(self):
        store=Store()
        engine,workflow=setup_engine(store,lambda args:args)
        digest=hashlib.sha256(json.dumps(asdict(workflow),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        store.start("abandoned",workflow.workflow_id,workflow.version,digest,principal_id="alice")
        self.assertTrue(store.claim("abandoned",principal_id="alice",token="crashed-process"))
        run=engine.run(workflow,request_id="abandoned",principal_id="alice",requested_grants={"local.read"})
        self.assertEqual(run.status,"BLOCKED")
        self.assertEqual(run.outputs,{})
        self.assertEqual(store.state("abandoned")[0],"RECEIVED")
        store.connection.close()

    def test_schema_error_not_logged_with_sensitive_payload(self):
        store=Store()
        engine,flow=setup_engine(store,lambda a:a)
        sensitive="private credential do not log 123"
        bad=Workflow("bad","1",(Step("one","local.read","1","worker",
                                  {"text":"ok","password":sensitive}),))
        response=engine.run(bad,request_id="privacy",principal_id="alice",requested_grants={"local.read"})
        self.assertEqual(response.status,"BLOCKED")
        self.assertNotIn(sensitive,repr(store.events("privacy")))
        self.assertNotIn(sensitive,response.reason)
        store.connection.close()

    def test_legacy_unbound_database_is_not_replayable(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/"legacy.db")
            conn=sqlite3.connect(db)
            conn.executescript("""
                CREATE TABLE executions(request_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                    workflow_version TEXT NOT NULL, spec_digest TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL);
                INSERT INTO executions VALUES('old','w','1','digest','COMPLETED',NULL,'2026-01-01');
            """)
            conn.close()
            store=Store(db)
            self.assertIn("principal_id",{row[1] for row in store.connection.execute("PRAGMA table_info(executions)")})
            with self.assertRaises(PermissionError):
                store.start("old","w","1","digest",principal_id="alice")
            store.connection.close()


if __name__=="__main__":unittest.main()
