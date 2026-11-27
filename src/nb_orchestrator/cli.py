"""Reproducible local demo: read -> transform -> validate in a sandbox."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from . import Agent, Capability, Engine, Registry, Step, Store, Workflow


def demo(db: str) -> dict:
    reg = Registry()
    obj = {"type":"object","additionalProperties":False,"required":["text"],"properties":{"text":{"type":"string"}}}
    result = {"type":"object","additionalProperties":False,"required":["text"],"properties":{"text":{"type":"string"}}}
    reg.register(Capability("sandbox","read_text","1",("read","research"),"P0",obj,result))
    reg.register(Capability("sandbox","summarize","1",("transform","analysis"),"P0",obj,result))
    reg.register(Capability("sandbox","verify","1",("verify","quality"),"P0",obj,{"type":"object","required":["valid","text"],"properties":{"valid":{"type":"boolean"},"text":{"type":"string"}}}))
    adapters={
       "sandbox.read_text":lambda a:{"text":a["text"]},
       "sandbox.summarize":lambda a:{"text":a["text"].strip()[:120]},
       "sandbox.verify":lambda a:{"valid":len(a["text"])>0,"text":a["text"]},
    }
    agents={"researcher":Agent("researcher",frozenset({"sandbox.read_text","sandbox.summarize"})),
            "verifier":Agent("verifier",frozenset({"sandbox.verify"}))}
    workflow=Workflow("read-summarize-verify","1",(
        Step("read","sandbox.read_text","1","researcher",{"text":"NeuralBlitz coordinates research, engineering, and validation agents."}),
        Step("summarize","sandbox.summarize","1","researcher",{"text":{"$ref":"read.text"}},("read",)),
        Step("verify","sandbox.verify","1","verifier",{"text":{"$ref":"summarize.text"}},("summarize",)),
    ))
    store=Store(db)
    try:
        response=Engine(reg,store,agents,adapters).run(workflow,request_id="demo-001",principal_id="local-cli",requested_grants=set(adapters))
        return {"status":response.status,"outputs":response.outputs,"reason":response.reason,"events":store.events("demo-001")}
    finally:
        store.connection.close()


def main() -> None:
    p=argparse.ArgumentParser(description="NeuralBlitz UPAOI local prototype")
    p.add_argument("command",choices=["demo","agents","sources","health","audit-verify"])
    p.add_argument("--db",default=":memory:")
    p.add_argument("--audit-db",help="Existing gateway audit SQLite file (audit-verify only)")
    p.add_argument("--principal-id",default="local-cli",help="Operator-scoped local identity label; NOT authentication")
    p.add_argument("--request-id",default="sources-001")
    p.add_argument("--repo",help="Explicit allowed GitHub owner/repository for read-only source collection")
    p.add_argument("--page-id",help="Explicit allowed Notion page UUID for read-only collection")
    p.add_argument("--inventory",default="data/plugin-health-2026-11-22.json")
    p.add_argument("--fixture",action="store_true",help="Use synthetic providers; never calls live APIs")
    args=p.parse_args()
    if args.command=="demo":
        print(json.dumps(demo(args.db),indent=2,ensure_ascii=False))
    elif args.command=="agents":
        from .agent_workflow import demo_agents
        print(json.dumps(demo_agents(args.db,principal_id=args.principal_id),indent=2,ensure_ascii=False))
    elif args.command=="health":
        from .health import HealthSnapshot
        snapshot=HealthSnapshot.from_file(args.inventory)
        print(json.dumps({"date":snapshot.date,"observations":len(snapshot.entries),
                          "counts":snapshot.counts(),"blocked":snapshot.blocked(),
                          "warning":"These are historical probes, not live access grants."},indent=2))
    elif args.command=="audit-verify":
        from .enterprise_audit import AuditJournal, AuditIntegrityError
        if not args.audit_db or not Path(args.audit_db).is_file():
            p.error("audit-verify requires --audit-db referring to an existing database file")
        encoded=os.environ.get("UPAOI_AUDIT_KEY_HEX", "")
        try:
            key=bytes.fromhex(encoded)
        except ValueError:
            p.error("UPAOI_AUDIT_KEY_HEX must be valid hex from a protected environment")
        if len(key)<32:
            p.error("UPAOI_AUDIT_KEY_HEX signing key must be at least 32 bytes")
        audit=AuditJournal(args.audit_db,signing_key=key)
        try:
            verified=audit.verify()
        except AuditIntegrityError:
            p.error("audit chain integrity check failed; halt admission and investigate")
        finally:
            audit.close()
        print(json.dumps(verified,indent=2))
    elif args.command=="sources":
        if not args.repo or not args.page_id:
            p.error("sources requires --repo OWNER/REPO and --page-id NOTION_UUID")
        from .integration_workflow import run_read_only_sources
        options = {}
        request_id = args.request_id
        if args.fixture:
            from .fixtures import fixture_readers
            readers = fixture_readers(args.repo,args.page_id)
            options = {"github_reader":readers[0],"notion_reader":readers[1]}
            request_id = "fixture-" + request_id
        result = run_read_only_sources(args.db, request_id=request_id,principal_id=args.principal_id,
                     repo=args.repo, page_id=args.page_id,**options)
        result["mode"] = "synthetic_fixture" if args.fixture else "live_read_only"
        print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
