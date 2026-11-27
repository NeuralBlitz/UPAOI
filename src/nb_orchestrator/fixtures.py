"""Obviously synthetic provider-shaped results for safe, repeatable CLI demos."""
from __future__ import annotations

from .providers import GithubRepositoryReader, NotionPageReader, canonical_page_id


def fixture_readers(repo: str, page_id: str):
    page_id = canonical_page_id(page_id)

    def github_get(path, headers, params):
        return {"full_name": repo, "html_url": "https://github.com/" + repo,
                "default_branch": "main", "private": False, "archived": False}

    def notion_get(path, headers, params):
        if path.startswith("/v1/pages/"):
            return {"object": "page", "id": page_id,
                    "url": "https://www.notion.so/" + page_id.replace("-", ""),
                    "last_edited_time": "2000-01-01T00:00:00.000Z",
                    "properties": {"title": {"type": "title", "title": [{"plain_text": "SYNTHETIC TEST FIXTURE — not live content"}]}}}
        return {"results": [{"type": "paragraph", "has_children": False,
                              "paragraph": {"rich_text": [{"plain_text": "Test-only data; not a provider fact."}]}}],
                "has_more": False}

    return (GithubRepositoryReader({repo}, transport=github_get, token_getter=lambda: ""),
            NotionPageReader({page_id}, transport=notion_get, token_getter=lambda: "fixture-secret"))
