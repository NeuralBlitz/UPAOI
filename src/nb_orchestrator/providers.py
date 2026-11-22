"""Explicit, read-only, allowlisted GitHub and Notion REST adapters.

No ChatGPT connector credentials are available to standalone Python. These adapters
use separate, least-privilege credentials supplied by the operator at runtime.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


class ProviderError(RuntimeError):
    """Sanitized provider error; do not expose body or secret-bearing headers."""


class AuthorizationError(ProviderError):
    pass


class DataIntegrityError(ProviderError):
    pass


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ReadOnlyTransport:
    host: str
    timeout_seconds: float = 8
    max_json_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.host not in ("https://api.github.com", "https://api.notion.com"):
            raise ValueError("transport host not permitted")
        if self.timeout_seconds <= 0 or not 0 < self.max_json_bytes <= 4_194_304:
            raise ValueError("invalid resource limit")

    def get(self, path: str, headers: dict[str, str], params: dict[str, str] | None = None) -> dict[str, Any]:
        # Paths are constructed by adapter code, never accepted as caller URL input.
        if not path.startswith("/") or ".." in path or "//" in path or "\\" in path or "?" in path:
            raise ValueError("invalid API path")
        url = self.host + path
        if params:
            url += "?" + urlencode(params)
        opener = build_opener(_NoRedirects())
        req = Request(url, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=self.timeout_seconds) as response:
                data = response.read(self.max_json_bytes + 1)
        except HTTPError as exc:
            # Intentionally suppress response body (may contain sensitive details).
            raise ProviderError(f"provider returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("provider transport unavailable") from None
        if len(data) > self.max_json_bytes:
            raise ProviderError("provider response exceeds size limit")
        try:
            obj = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise ProviderError("provider returned invalid JSON") from None
        if not isinstance(obj, dict):
            raise DataIntegrityError("provider JSON object expected")
        return obj


_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})$")
Transport = Callable[[str, dict[str, str], dict[str, str] | None], dict[str, Any]]


class GithubRepositoryReader:
    def __init__(self, allowed_repositories: set[str], *, transport: Transport | None = None,
                 token_getter: Callable[[], str] | None = None) -> None:
        self.allowed_repositories = frozenset(allowed_repositories)
        self.transport = transport or ReadOnlyTransport("https://api.github.com").get
        self.token_getter = token_getter or (lambda: os.environ.get("UPAOI_GITHUB_TOKEN", ""))

    def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        owner, repo = args["owner"], args["repo"]
        if not isinstance(owner, str) or not isinstance(repo, str) or not _OWNER.fullmatch(owner) or not _REPO_NAME.fullmatch(repo):
            raise ValueError("invalid GitHub repository identifier")
        name = f"{owner}/{repo}"
        if name not in self.allowed_repositories:
            raise AuthorizationError("GitHub repository not in explicit allowlist")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "NeuralBlitz-UPAOI/0.2.0",
                   "X-GitHub-Api-Version": "2026-03-10"}
        token = self.token_getter()
        if token:
            headers["Authorization"] = "Bearer " + token
        result = self.transport(f"/repos/{owner}/{repo}", headers, None)
        if result.get("full_name") != name or result.get("html_url") != f"https://github.com/{name}":
            raise DataIntegrityError("GitHub repository identity mismatch")
        branch = result.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise DataIntegrityError("GitHub default branch missing")
        return {"provider": "github", "full_name": name, "url": result["html_url"],
                "default_branch": branch, "private": bool(result.get("private", False)),
                "archived": bool(result.get("archived", False))}


def canonical_page_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("invalid Notion page UUID") from None


def notion_title(properties: dict[str, Any]) -> str:
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            rich = prop.get("title", [])
            if isinstance(rich, list):
                return "".join(item.get("plain_text", "") for item in rich if isinstance(item, dict))[:300] or "Untitled"
    return "Untitled"


class NotionPageReader:
    def __init__(self, allowed_pages: set[str], *, transport: Transport | None = None,
                 token_getter: Callable[[], str] | None = None) -> None:
        self.allowed_pages = frozenset(canonical_page_id(p) for p in allowed_pages)
        self.transport = transport or ReadOnlyTransport("https://api.notion.com").get
        self.token_getter = token_getter or (lambda: os.environ.get("UPAOI_NOTION_TOKEN", ""))

    def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        page_id = canonical_page_id(args["page_id"])
        if page_id not in self.allowed_pages:
            raise AuthorizationError("Notion page not in explicit allowlist")
        token = self.token_getter()
        if not token:
            raise AuthorizationError("UPAOI_NOTION_TOKEN is required for live Notion reads")
        headers = {"Authorization": "Bearer " + token, "Notion-Version": "2022-06-28",
                   "Accept": "application/json", "User-Agent": "NeuralBlitz-UPAOI/0.2.0"}
        page = self.transport(f"/v1/pages/{page_id}", headers, None)
        if canonical_page_id(page.get("id")) != page_id or page.get("object") != "page":
            raise DataIntegrityError("Notion page identity mismatch")
        blocks = self.transport(f"/v1/blocks/{page_id}/children", headers, {"page_size": "25"})
        items = blocks.get("results")
        if not isinstance(items, list):
            raise DataIntegrityError("Notion children response missing results")
        pieces: list[str] = []
        nested = False
        for item in items:
            if not isinstance(item, dict):
                continue
            nested = nested or bool(item.get("has_children"))
            typ = item.get("type", "")
            value = item.get(typ, {}) if isinstance(typ, str) else {}
            rich = value.get("rich_text", []) if isinstance(value, dict) else []
            if isinstance(rich, list):
                pieces.append("".join(part.get("plain_text", "") for part in rich if isinstance(part, dict)))
        excerpt = "\n".join(x for x in pieces if x)[:2000]
        url = page.get("url")
        if not isinstance(url, str) or not url.startswith("https://www.notion.so/") and not url.startswith("https://notion.so/"):
            # Notion may use the official app.notion.com link in modern clients.
            if not isinstance(url, str) or not url.startswith("https://app.notion.com/"):
                raise DataIntegrityError("Notion URL format unexpected")
        return {"provider": "notion", "page_id": page_id,
                "title": notion_title(page.get("properties", {})), "url": url,
                "last_edited_time": str(page.get("last_edited_time", "")),
                "text_excerpt": excerpt, "blocks_read": len(items),
                "truncated": bool(blocks.get("has_more") or nested or len(excerpt) >= 2000)}
