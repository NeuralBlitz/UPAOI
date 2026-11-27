"""Tests enforce bounded handoff contracts and untrusted-result isolation."""
import unittest
from nb_orchestrator.agent_runtime import (DispatchDenied, SpecialistContract,
                                           SpecialistRuntime, TaskPacket)

IN = {"type":"object","required":["text"],"additionalProperties":False,
      "properties":{"text":{"type":"string"}}}
OUT = {"type":"object","required":["summary"],"additionalProperties":False,
       "properties":{"summary":{"type":"string"}}}


class SpecialistRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.runtime=SpecialistRuntime()
        self.runtime.register(SpecialistContract("researcher","1",IN,OUT,
            frozenset({"notion:page-1"}),max_payload_bytes=256,max_output_bytes=256),
            lambda task:self.calls.append(task) or {"summary":task.payload["text"].upper()},
            reviewer_id="reviewer",reviewer=lambda task,out:out["summary"]==task.payload["text"].upper())
        self.packet=TaskPacket("task-1","researcher","1","Summarize provided text",
                               ("Summary matches transformed input",),
                               ("notion:page-1",),{"text":"hello"})

    def dispatch(self,packet=None,agents=None,sources=None,classes=None):
        return self.runtime.dispatch(packet or self.packet,
            authorized_agents={"researcher"} if agents is None else agents,
            authorized_sources={"notion:page-1"} if sources is None else sources,
            allowed_classifications={"public"} if classes is None else classes)

    def test_valid_result_includes_provenance_and_reviewer(self):
        response=self.dispatch()
        self.assertEqual(response["output"],{"summary":"HELLO"})
        self.assertEqual(response["source_refs"],["notion:page-1"])
        self.assertEqual(response["reviewer_id"],"reviewer")
        self.assertEqual(len(self.calls),1)

    def test_worker_not_authorized(self):
        with self.assertRaises(DispatchDenied):self.dispatch(agents=set())
        self.assertFalse(self.calls)

    def test_source_is_not_a_permission(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("github:private",),{"text":"hello"})
        with self.assertRaises(DispatchDenied):self.dispatch(packet,sources={"github:private"})
        self.assertFalse(self.calls)

    def test_caller_scope_must_allow_source(self):
        with self.assertRaises(DispatchDenied):self.dispatch(sources=set())
        self.assertFalse(self.calls)

    def test_classification_rejected_before_dispatch(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("notion:page-1",),{"text":"secret"},"restricted")
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_schema_invalid_payload(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("notion:page-1",),{"text":"hello", "tools":["admin.delete"]})
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_oversize_objective_fails_before_worker(self):
        packet=TaskPacket("task-1","researcher","1","x"*5000,("check",),
                          ("notion:page-1",),{"text":"hello"})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_unbounded_acceptance_list_fails_before_worker(self):
        packet=TaskPacket("task-1","researcher","1","summarize",("check",)*18,
                          ("notion:page-1",),{"text":"hello"})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_bounded_input(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("notion:page-1",),{"text":"a"*600})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_version_mismatch(self):
        packet=TaskPacket("task-1","researcher","2","Summarize",("check",),
                          ("notion:page-1",),{"text":"hello"})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_reviewer_rejection(self):
        runtime=SpecialistRuntime()
        runtime.register(SpecialistContract("researcher","1",IN,OUT,frozenset()),
                         lambda _: {"summary":"bad"},reviewer_id="verifier",reviewer=lambda *_:False)
        packet=TaskPacket("t","researcher","1","Summarize",("check",),(),{"text":"hello"})
        with self.assertRaises(DispatchDenied):runtime.dispatch(packet,authorized_agents={"researcher"},
                                        authorized_sources=set(),allowed_classifications={"public"})

    def test_duplicate_specialist_or_self_review_denied(self):
        c=SpecialistContract("researcher","1",IN,OUT,frozenset())
        with self.assertRaises(ValueError):self.runtime.register(c,lambda p:{},reviewer_id="other",reviewer=lambda *_:True)
        with self.assertRaises(ValueError):SpecialistRuntime().register(c,lambda p:{},reviewer_id="researcher",reviewer=lambda *_:True)

    def test_reject_invalid_specialist_output_schema(self):
        from jsonschema import ValidationError
        runtime=SpecialistRuntime()
        runtime.register(SpecialistContract("researcher","1",IN,OUT,frozenset()),
                         lambda p:{"summary":5},reviewer_id="reviewer",reviewer=lambda *_:True)
        packet=TaskPacket("task","researcher","1","Summarize",("check",),(),{"text":"hello"})
        with self.assertRaises(ValidationError):runtime.dispatch(packet,
                    authorized_agents={"researcher"}, authorized_sources=set(),allowed_classifications={"public"})

    def test_duplicate_context_reference_is_denied(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("notion:page-1","notion:page-1"),{"text":"hello"})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_non_json_payload_rejected(self):
        packet=TaskPacket("task-1","researcher","1","Summarize",("check",),
                          ("notion:page-1",),{"text":set(["unexpected"])})
        with self.assertRaises(DispatchDenied):self.dispatch(packet)
        self.assertFalse(self.calls)

    def test_oversize_specialist_output_rejected(self):
        runtime=SpecialistRuntime()
        runtime.register(SpecialistContract("researcher","1",IN,OUT,frozenset(),max_output_bytes=25),
                         lambda p:{"summary":"s"*500},reviewer_id="reviewer",reviewer=lambda *_:True)
        packet=TaskPacket("task","researcher","1","Summarize",("check",),(),{"text":"hello"})
        with self.assertRaises(DispatchDenied):runtime.dispatch(packet,
                    authorized_agents={"researcher"},authorized_sources=set(),allowed_classifications={"public"})

    def test_untrusted_worker_cannot_mutate_original_payload(self):
        runtime=SpecialistRuntime()
        def mutate(packet):
            packet.payload["text"]="changed"
            return {"summary":"HELLO"}
        runtime.register(SpecialistContract("researcher","1",IN,OUT,frozenset()),
                         mutate,reviewer_id="reviewer",reviewer=lambda p,o: p.payload["text"]=="hello")
        p=TaskPacket("t","researcher","1","do task",("check",),(),{"text":"hello"})
        result=runtime.dispatch(p,authorized_agents={"researcher"},authorized_sources=set(),allowed_classifications={"public"})
        self.assertEqual(result["output"]["summary"],"HELLO")
        self.assertEqual(p.payload["text"],"hello")


class AgentWorkflowTests(unittest.TestCase):
    def test_two_specialists_complete_with_reviewers(self):
        from nb_orchestrator.agent_workflow import demo_agents
        r=demo_agents()
        self.assertEqual(r["status"],"COMPLETED",r["reason"])
        self.assertEqual(r["mode"],"deterministic_host_callbacks_no_llm_no_network")
        self.assertEqual(r["outputs"]["analysis"]["agent_id"],"analyst")
        self.assertEqual(r["outputs"]["audit"]["agent_id"],"auditor")
        self.assertEqual(r["outputs"]["analysis"]["reviewer_id"],"analyst-reviewer")
        self.assertEqual(r["outputs"]["audit"]["reviewer_id"],"audit-reviewer")
        self.assertTrue(r["outputs"]["audit"]["output"]["accepted"])

    def test_two_specialist_workflow_cache_stable(self):
        import tempfile
        from pathlib import Path
        from nb_orchestrator.agent_workflow import demo_agents
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/"agents.sqlite")
            a=demo_agents(db)
            b=demo_agents(db)
            self.assertEqual(a["status"],"COMPLETED")
            self.assertEqual(b["status"],"COMPLETED")
            self.assertEqual(a["event_count"],b["event_count"])
            c=demo_agents(db,principal_id="different-principal")
            self.assertEqual(c["status"],"BLOCKED")
            self.assertEqual(c["outputs"],{})


if __name__=="__main__":unittest.main()
