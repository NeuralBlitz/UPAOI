"""Two-provider, read-only workflow with explicit data/provenance boundaries."""
from __future__ import annotations

import os
from . import Agent, Capability, Engine, Registry, Step, Store, Workflow
from .providers import GithubRepositoryReader, NotionPageReader, canonical_page_id


def build_integration_engine(store: Store, *, allowed_repo: str, allowed_page: str,
                             github_reader=None, notion_reader=None):
    page_id = canonical_page_id(allowed_page)
    owner, repo = allowed_repo.split("/", 1)
    reg = Registry()
    reg.register(Capability("github", "repository_read", "2026-11-22", ("code", "repo", "research"), "P0",
        {"type":"object","required":["owner","repo"],"additionalProperties":False,
         "properties":{"owner":{"type":"string"},"repo":{"type":"string"}}},
        {"type":"object","required":["provider","full_name","url","default_branch","private","archived"],
         "properties":{"provider":{"const":"github"},"full_name":{"type":"string"},"url":{"type":"string"},
          "default_branch":{"type":"string"},"private":{"type":"boolean"},"archived":{"type":"boolean"}},
         "additionalProperties":False}, scopes=("github:repository:read",)))
    reg.register(Capability("notion", "page_read", "2026-11-22", ("knowledge", "docs", "research"), "P0",
        {"type":"object","required":["page_id"],"additionalProperties":False,"properties":{"page_id":{"type":"string"}}},
        {"type":"object","required":["provider","page_id","title","url","last_edited_time","text_excerpt","blocks_read","truncated"],
         "properties":{"provider":{"const":"notion"},"page_id":{"type":"string"},"title":{"type":"string"},
          "url":{"type":"string"},"last_edited_time":{"type":"string"},"text_excerpt":{"type":"string"},
          "blocks_read":{"type":"integer"},"truncated":{"type":"boolean"}},"additionalProperties":False},
        scopes=("notion:page:read",)))
    reg.register(Capability("local", "evidence_manifest", "2026-11-22", ("verify", "provenance"), "P0",
        {"type":"object","required":["github_url","notion_url"],"additionalProperties":False,
         "properties":{"github_url":{"type":"string"},"notion_url":{"type":"string"}}},
        {"type":"object","required":["source_urls","status"],"additionalProperties":False,
         "properties":{"source_urls":{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":2},
          "status":{"const":"recorded_not_independently_verified"}}}))
    workflow = Workflow("github-notion-source-inventory","0.2.0",(
        Step("repo", "github.repository_read", "2026-11-22", "collector", {"owner":owner,"repo":repo}),
        Step("page", "notion.page_read", "2026-11-22", "collector", {"page_id":page_id}),
        Step("manifest", "local.evidence_manifest", "2026-11-22", "verifier",
             {"github_url":{"$ref":"repo.url"}, "notion_url":{"$ref":"page.url"}}, ("repo","page")),
    ))
    adapters={
        "github.repository_read":github_reader if github_reader is not None else GithubRepositoryReader({allowed_repo}),
        "notion.page_read":notion_reader if notion_reader is not None else NotionPageReader({page_id}),
        "local.evidence_manifest":lambda a:{"source_urls":[a["github_url"],a["notion_url"]],
                                             "status":"recorded_not_independently_verified"},
    }
    agents={"collector":Agent("collector",frozenset({"github.repository_read","notion.page_read"})),
            "verifier":Agent("verifier",frozenset({"local.evidence_manifest"}))}
    return Engine(reg,store,agents,adapters),workflow


def run_read_only_sources(db: str, *, request_id: str, repo: str, page_id: str, github_reader=None, notion_reader=None):
    store=Store(db)
    engine,workflow=build_integration_engine(store,allowed_repo=repo,allowed_page=page_id,
                                              github_reader=github_reader,notion_reader=notion_reader)
    result=engine.run(workflow,request_id=request_id,
                      requested_grants={"github.repository_read","notion.page_read","local.evidence_manifest"},
                      execution_scopes={"github:repository:read","notion:page:read"})
    return {"status":result.status,"reason":result.reason,"outputs":result.outputs,
            "event_count":len(store.events(request_id))}
