"""A reproducible multi-specialist, independently reviewed LOCAL demo.

This demonstrates typed handoffs and provenance through the core DAG engine,
using deterministic callbacks. It does NOT call any LLM, plugin, or external API.
"""
from __future__ import annotations

from .agent_runtime import SpecialistContract, SpecialistRuntime, TaskPacket
from .engine import Engine
from .models import Agent, Capability, Step, Workflow
from .registry import Registry
from .store import Store

SOURCE = "fixture:neuralblitz-upaoi"
IN_TEXT = {"type":"object", "required":["text"], "additionalProperties":False,
           "properties":{"text":{"type":"string","minLength":1,"maxLength":4000}}}
OUT_SUMMARY = {"type":"object", "required":["summary"], "additionalProperties":False,
               "properties":{"summary":{"type":"string","minLength":1}}}
IN_SUMMARY = {"type":"object", "required":["summary"], "additionalProperties":False,
              "properties":{"summary":{"type":"string","minLength":1}}}
OUT_AUDIT = {"type":"object", "required":["accepted","reason"], "additionalProperties":False,
             "properties":{"accepted":{"const":True},"reason":{"type":"string"}}}
HANDOFF = {"type":"object","additionalProperties":False,
    "required":["task_id","agent_id","agent_version","reviewer_id","review_status","source_refs","output"],
    "properties":{"task_id":{"type":"string"},"agent_id":{"type":"string"},
                  "agent_version":{"type":"string"},"reviewer_id":{"type":"string"},
                  "review_status":{"const":"accepted_by_registered_reviewer"},
                  "source_refs":{"type":"array","items":{"type":"string"}},
                  "output":{"type":"object"}}}


def demo_agents(db: str = ":memory:", *, principal_id: str = "local-cli") -> dict:
    runtime = SpecialistRuntime()
    runtime.register(SpecialistContract("analyst", "1", IN_TEXT, OUT_SUMMARY,
                                       frozenset({SOURCE})),
        lambda packet: {"summary":packet.payload["text"].strip()[:240]},
        reviewer_id="analyst-reviewer",
        reviewer=lambda packet, output: output["summary"] == packet.payload["text"].strip()[:240])
    runtime.register(SpecialistContract("auditor", "1", IN_SUMMARY, OUT_AUDIT,
                                       frozenset({SOURCE})),
        lambda packet: {"accepted":True,"reason":"nonempty summary submitted"},
        reviewer_id="audit-reviewer",
        reviewer=lambda packet, output: bool(packet.payload["summary"].strip()) and
               output["accepted"] is True and output["reason"]=="nonempty summary submitted")
    registry = Registry()
    registry.register(Capability("local", "analyze", "1", ("analysis", "research"), "P0",
                                 IN_TEXT, HANDOFF))
    registry.register(Capability("local", "audit", "1", ("verification", "research"), "P0",
                                 IN_SUMMARY, HANDOFF))
    def adapter(agent_id: str, task_id: str, objective: str, criteria: str, field: str):
        def invoke(args):
            packet = TaskPacket(task_id, agent_id, "1", objective, (criteria,), (SOURCE,), args)
            return runtime.dispatch(packet, authorized_agents={agent_id},
                                    authorized_sources={SOURCE}, allowed_classifications={"public"})
        return invoke
    adapters = {
        "local.analyze": adapter("analyst", "analysis-001", "Produce an excerpt of a supplied fixture",
                                 "Excerpt equals a bounded prefix of the fixture text", "text"),
        "local.audit": adapter("auditor", "audit-001", "Check the analyst excerpt is nonempty",
                               "An independent registered reviewer accepts the contract", "summary"),
    }
    agents = {"analyst": Agent("analyst", frozenset({"local.analyze"})),
              "auditor": Agent("auditor", frozenset({"local.audit"}))}
    flow = Workflow("two-specialist-reviewed-demo", "0.3.0", (
        Step("analysis", "local.analyze", "1", "analyst",
             {"text":"NeuralBlitz coordinates bounded specialist agents with independently checked outputs."}),
        Step("audit", "local.audit", "1", "auditor",
             {"summary":{"$ref":"analysis.output.summary"}}, ("analysis",)),
    ))
    store = Store(db)
    try:
        result = Engine(registry, store, agents, adapters).run(
            flow, request_id="agents-demo-001", principal_id=principal_id,
            requested_grants={"local.analyze", "local.audit"})
        return {"status": result.status, "reason": result.reason, "outputs": result.outputs,
                "event_count": len(store.events("agents-demo-001")),
                "mode": "deterministic_host_callbacks_no_llm_no_network"}
    finally:
        store.connection.close()
