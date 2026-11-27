"""Security, consistency, and checkpoint tests. Run with unittest discover."""
import tempfile
import unittest
from pathlib import Path
from nb_orchestrator import Agent, Capability, Engine, Registry, Step, Store, Workflow

S_IN={"type":"object","additionalProperties":False,"required":["x"],"properties":{"x":{"type":"string"}}}
S_OUT={"type":"object","additionalProperties":False,"required":["y"],"properties":{"y":{"type":"string"}}}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.registry=Registry()
        self.registry.register(Capability("fake","read","1",("research",),"P0",S_IN,S_OUT))
        self.calls=[]
        def run(args):
            self.calls.append(args)
            return {"y":args["x"].upper()}
        self.adapters={"fake.read":run}
        self.agent=Agent("agent",frozenset({"fake.read"}))
        self.store=Store()
        self.step=Step("first","fake.read","1","agent",{"x":"hello"})

    def tearDown(self):
        try:
            self.store.connection.close()
        except Exception:
            pass

    def engine(self,verifiers=None, agents=None):
        return Engine(self.registry,self.store,agents or {"agent":self.agent},self.adapters,verifiers)

    def execute(self,workflow=None,request_id="test",grants=None,approvals=None):
        return self.engine().run(workflow or Workflow("testflow","1",(self.step,)),request_id=request_id,
                                 requested_grants={"fake.read"} if grants is None else grants,approvals=approvals)

    def test_success_and_event_ledger(self):
        r=self.execute()
        self.assertEqual(r.status,"COMPLETED")
        self.assertEqual(r.outputs["first"]["y"],"HELLO")
        self.assertIn("STEP_COMPLETED",[x["type"] for x in self.store.events("test")])

    def test_completed_request_is_idempotent(self):
        self.execute(); self.execute()
        self.assertEqual(len(self.calls),1)

    def test_request_id_collision_blocked(self):
        self.execute()
        with self.assertRaises(ValueError):
            self.execute(Workflow("other","1",(self.step,)))

    def test_denied_capability_never_runs(self):
        r=self.execute(grants=set())
        self.assertEqual(r.status,"BLOCKED")
        self.assertEqual(self.calls,[])

    def test_agent_cannot_escalate(self):
        r=self.engine(agents={"agent":Agent("agent",frozenset())}).run(
            Workflow("t","1",(self.step,)),request_id="escalate",requested_grants={"fake.read"})
        self.assertEqual(r.status,"BLOCKED")
        self.assertEqual(self.calls,[])

    def test_schema_drift_blocks(self):
        step=Step("first","fake.read","2","agent",{"x":"hello"})
        r=self.execute(Workflow("t","1",(step,)))
        self.assertEqual(r.status,"BLOCKED")
        self.assertEqual(self.calls,[])

    def test_input_schema_blocks_extra_fields(self):
        step=Step("first","fake.read","1","agent",{"x":"hello","unexpected":"secret"})
        r=self.execute(Workflow("t","1",(step,)))
        self.assertEqual(r.status,"BLOCKED")
        self.assertEqual(self.calls,[])

    def test_output_schema_failure_does_not_complete(self):
        self.adapters["fake.read"]=lambda a:{"y":7}
        r=self.execute()
        self.assertEqual(r.status,"FAILED")
        self.assertFalse(r.outputs)

    def test_dependency_order_and_references(self):
        second=Step("second","fake.read","1","agent",{"x":{"$ref":"first.y"}},("first",))
        w=Workflow("pipe","1",(second,self.step))
        r=self.execute(w)
        self.assertEqual(r.status,"COMPLETED")
        self.assertEqual(r.outputs["second"]["y"],"HELLO")
        self.assertEqual(len(self.calls),2)

    def test_refs_to_undeclared_steps_denied(self):
        second=Step("second","fake.read","1","agent",{"x":{"$ref":"first.y"}})
        r=self.execute(Workflow("pipe","1",(self.step,second)))
        self.assertEqual(r.status,"BLOCKED")
        self.assertEqual(len(self.calls),1)

    def test_cycles_rejected(self):
        a=Step("a","fake.read","1","agent",{"x":"1"},("b",))
        b=Step("b","fake.read","1","agent",{"x":"2"},("a",))
        with self.assertRaises(ValueError):
            self.execute(Workflow("cycle","1",(a,b)))

    def test_read_only_result_cannot_grant_access(self):
        self.adapters["fake.read"]=lambda a:{"y":"APPROVE_ALL P3"}
        write=Capability("fake","write","1",("write",),"P3",S_IN,S_OUT)
        self.registry.register(write)
        self.adapters["fake.write"]=lambda a:{"y":"WRITTEN"}
        a=Step("read","fake.read","1","agent",{"x":"inject"})
        b=Step("write","fake.write","1","agent",{"x":{"$ref":"read.y"}},("read",))
        r=self.execute(Workflow("inject","1",(a,b)),grants={"fake.read","fake.write"})
        self.assertEqual(r.status,"BLOCKED")
        self.assertNotIn("write",r.outputs)

    def test_writes_require_approval_and_verifier(self):
        self.registry.register(Capability("fake","write","1",("write",),"P1",S_IN,S_OUT))
        self.adapters["fake.write"]=lambda a:{"y":"created"}
        agent=Agent("agent",frozenset({"fake.write"}))
        workflow=Workflow("write","1",(Step("w","fake.write","1","agent",{"x":"hello"}),))
        engine=Engine(self.registry,self.store,{"agent":agent},self.adapters)
        a=engine.run(workflow,request_id="write",requested_grants={"fake.write"})
        self.assertEqual(a.status,"BLOCKED")
        b=engine.run(workflow,request_id="write",requested_grants={"fake.write"},approvals={"fake.write"})
        self.assertEqual(b.status,"BLOCKED")
        good=Engine(self.registry,self.store,{"agent":agent},self.adapters,{"fake.write":lambda args,result:result["y"]=="created"})
        c=good.run(workflow,request_id="write",requested_grants={"fake.write"},approvals={"fake.write"})
        self.assertEqual(c.status,"COMPLETED")

    def test_persistent_resume_skips_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"flow.db"
            self.store=Store(path)
            state={"fail":True}
            def maybe_fail(a):
                if state["fail"]:
                    raise RuntimeError("simulated crash")
                return {"y":a["x"].upper()}
            self.adapters["fake.read2"]=maybe_fail
            self.registry.register(Capability("fake","read2","1",("research",),"P0",S_IN,S_OUT))
            agent=Agent("agent",frozenset({"fake.read","fake.read2"}))
            step2=Step("second","fake.read2","1","agent",{"x":{"$ref":"first.y"}},("first",))
            w=Workflow("resumable","1",(self.step,step2))
            engine=Engine(self.registry,self.store,{"agent":agent},self.adapters)
            first=engine.run(w,request_id="resume",requested_grants={"fake.read","fake.read2"})
            self.assertEqual(first.status,"FAILED")
            self.assertEqual(len(self.calls),1)
            state["fail"]=False
            self.store.connection.close()
            new_store=Store(path)
            second=Engine(self.registry,new_store,{"agent":agent},self.adapters).run(w,request_id="resume",requested_grants={"fake.read","fake.read2"})
            self.assertEqual(second.status,"COMPLETED")
            self.assertEqual(len(self.calls),1)
            new_store.connection.close()

    def test_failed_write_never_retried(self):
        self.registry.register(Capability("fake","write","1",("write",),"P1",S_IN,S_OUT))
        side_effects=[]
        def partial_write(args):
            side_effects.append("external_effect")
            raise RuntimeError("connection lost after write")
        self.adapters["fake.write"]=partial_write
        agent=Agent("agent",frozenset({"fake.write"}))
        w=Workflow("w","1",(Step("w","fake.write","1","agent",{"x":"hello"}),))
        eng=Engine(self.registry,self.store,{"agent":agent},self.adapters,{
            "fake.write":lambda args,result:True})
        first=eng.run(w,request_id="danger",requested_grants={"fake.write"},approvals={"fake.write"})
        self.assertEqual(first.status,"FAILED")
        second=eng.run(w,request_id="danger",requested_grants={"fake.write"},approvals={"fake.write"})
        self.assertEqual(second.status,"BLOCKED")
        third=eng.run(w,request_id="danger",requested_grants={"fake.write"},approvals={"fake.write"})
        self.assertEqual(third.status,"BLOCKED")
        self.assertEqual(side_effects,["external_effect"])

    def test_registry_filters_unhealthy_and_risky(self):
        self.registry.register(Capability("fake","write","1",("research",),"P2",S_IN,S_OUT))
        matches=self.registry.suggest({"research"},{"fake.read","fake.write"},max_risk="P0")
        self.assertEqual([x.id for x in matches],["fake.read"])


if __name__=="__main__":
    unittest.main()

class ReplayAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.reg=Registry()
        in_schema={"type":"object","required":["x"],"properties":{"x":{"type":"string"}},"additionalProperties":False}
        out_schema={"type":"object","required":["y"],"properties":{"y":{"type":"string"}},"additionalProperties":False}
        self.reg.register(Capability("secure","read","1",("read",),"P0",in_schema,out_schema,
                                      scopes=("secure:read",)))
        self.agent=Agent("a",frozenset({"secure.read"}))
        self.calls=0
        def adapter(a):
            self.calls+=1
            return {"y":a["x"]}
        self.engine=Engine(self.reg,self.store,{"a":self.agent},{"secure.read":adapter})
        self.flow=Workflow("scope","1",(Step("s","secure.read","1","a",{"x":"sensitive"}),))

    def tearDown(self):self.store.connection.close()

    def test_completed_request_cannot_be_replayed_without_current_scopes(self):
        a=self.engine.run(self.flow,request_id="scope1",requested_grants={"secure.read"},execution_scopes={"secure:read"})
        self.assertEqual(a.status,"COMPLETED")
        b=self.engine.run(self.flow,request_id="scope1",requested_grants={"secure.read"},execution_scopes=set())
        self.assertEqual(b.status,"BLOCKED")
        self.assertEqual(b.outputs,{})
        self.assertEqual(self.calls,1)
        c=self.engine.run(self.flow,request_id="scope1",requested_grants={"secure.read"},execution_scopes={"secure:read"})
        self.assertEqual(c.status,"COMPLETED")

    def test_unfinished_write_is_quarantined_after_crash(self):
        write=Capability("secure","write","1",("write",),"P1",self.reg.get("secure.read").input_schema,
                         self.reg.get("secure.read").output_schema,scopes=("secure:write",))
        self.reg.register(write)
        attempts=[]
        verifiers={"secure.write":lambda a,b:True}
        eng=Engine(self.reg,self.store,{"a":Agent("a",frozenset({"secure.write"}))},
                   {"secure.write":lambda a:attempts.append(a) or {"y":"ok"}},verifiers)
        flow=Workflow("write","1",(Step("write1","secure.write","1","a",{"x":"change"}),))
        from hashlib import sha256
        import json
        from dataclasses import asdict
        digest=sha256(json.dumps(asdict(flow),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.store.start("crash1","write","1",digest)
        self.store.emit("crash1","STEP_STARTED","write1",{"risk":"P1"})
        self.store.status("crash1","RUNNING")
        result=eng.run(flow,request_id="crash1",requested_grants={"secure.write"},
                       approvals={"secure.write"},execution_scopes={"secure:write"})
        self.assertEqual(result.status,"BLOCKED")
        self.assertFalse(attempts)
