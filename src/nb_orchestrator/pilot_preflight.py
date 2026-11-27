"""Explicit-credential, read-only identity + provider preflight for M3.

This module never obtains ChatGPT plugin tokens, performs no writes, and is
not a production integration certification. Live execution requires operator-
provisioned credentials in a protected runtime environment.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from .enterprise_auth import AuthenticationDenied, OidcVerifier, VerifiedIdentity
from .fixtures import fixture_readers
from .providers import (GithubRepositoryReader, NotionPageReader, canonical_page_id)

REQUIRED_SCOPES = frozenset({'github:repository:read', 'notion:page:read'})


class PreflightFailed(RuntimeError):
    """No raw token, HTTP response body or caller input in exception text."""


def verify_source_reads(*, repo: str, page_id: str,
                        github_reader: Callable[[dict[str, str]], dict[str, Any]],
                        notion_reader: Callable[[dict[str, str]], dict[str, Any]],
                        identity: VerifiedIdentity | None = None,
                        allowed_tenant: str | None = None) -> dict[str, Any]:
    """Perform only GET-like reader calls and return a deliberately minimal receipt.

    Synthetic fixtures have no identity and are always marked SIMULATED_ONLY.
    A live receipt requires a freshly validated identity and read scopes.
    The caller is responsible for supplying independently allowlisted readers.
    """
    try:
        if not isinstance(repo, str) or repo.count('/') != 1:
            raise ValueError('invalid repository identifier')
        owner, name = repo.split('/')
        if not owner or not name or len(repo) > 150:
            raise ValueError('invalid repository identifier')
        canonical_page = canonical_page_id(page_id)
        if identity is not None:
            if not isinstance(identity, VerifiedIdentity) or allowed_tenant is None:
                raise ValueError('untrusted identity state')
            if identity.tenant_id != allowed_tenant or not REQUIRED_SCOPES.issubset(identity.scopes):
                raise ValueError('identity scope or tenant denied')
        elif allowed_tenant is not None:
            raise ValueError('missing verified identity')
    except (ValueError, TypeError, AttributeError):
        raise PreflightFailed('preflight authorization or source configuration rejected') from None
    try:
        github = github_reader({'owner': owner, 'repo': name})
        notion = notion_reader({'page_id': canonical_page})
        if (not isinstance(github, dict) or github.get('provider') != 'github'
                or github.get('full_name') != repo
                or github.get('url') != 'https://github.com/' + repo
                or not isinstance(notion, dict) or notion.get('provider') != 'notion'
                or notion.get('page_id') != canonical_page):
            raise ValueError('provider response did not match source')
    except Exception:
        # Provider bodies, source excerpts and secrets MUST NOT reach logs.
        raise PreflightFailed('read-only source preflight failed') from None
    canonical = json.dumps({'repo': repo, 'page': canonical_page}, sort_keys=True,
                           separators=(',', ':'))
    return {
        'status': 'READ_ONLY_SOURCES_REACHED' if identity is not None else 'SIMULATED_ONLY',
        'identity': 'pinned_jwks_signed_token' if identity is not None else 'not_tested_fixture',
        'github': {'identity_match': True, 'operation': 'GET repository'},
        'notion': {'identity_match': True, 'operation': 'GET page and bounded child blocks'},
        'configured_sources_digest': hashlib.sha256(canonical.encode()).hexdigest(),
        'claims_verified': identity is not None,
        'content_claims_independently_verified': False,
        'release_approved': False,
    }


def run_fixture_preflight(repo: str, page_id: str) -> dict[str, Any]:
    try:
        github, notion = fixture_readers(repo, page_id)
        return verify_source_reads(repo=repo, page_id=page_id,
                                   github_reader=github, notion_reader=notion)
    except PreflightFailed:
        raise
    except Exception:
        raise PreflightFailed('invalid fixture source configuration') from None


def run_configured_preflight(environ: Mapping[str, str], *,
                             github_reader: Callable[[dict[str, str]], dict[str, Any]] | None = None,
                             notion_reader: Callable[[dict[str, str]], dict[str, Any]] | None = None
                             ) -> dict[str, Any]:
    """Opt-in live smoke with separate trusted IdP and provider credentials.

    Does not reuse the ChatGPT connector authorization context and will NEVER
    fetch provider API secrets automatically.
    """
    required = (
        'UPAOI_OIDC_ISSUER', 'UPAOI_OIDC_AUDIENCE', 'UPAOI_OIDC_JWKS_JSON',
        'UPAOI_TENANT_ID', 'UPAOI_OIDC_TEST_ACCESS_TOKEN',
        'UPAOI_ALLOWED_REPO', 'UPAOI_ALLOWED_NOTION_PAGE',
        'UPAOI_GITHUB_TOKEN', 'UPAOI_NOTION_TOKEN',
    )
    if any(not isinstance(environ.get(key), str) or not environ[key] for key in required):
        raise PreflightFailed('missing protected M3 preflight configuration')
    try:
        jwks = json.loads(environ['UPAOI_OIDC_JWKS_JSON'])
        verifier = OidcVerifier(issuer=environ['UPAOI_OIDC_ISSUER'],
                                audience=environ['UPAOI_OIDC_AUDIENCE'], jwks=jwks)
        identity = verifier.verify(environ['UPAOI_OIDC_TEST_ACCESS_TOKEN'])
    except (AuthenticationDenied, ValueError, TypeError, KeyError, ImportError):
        raise PreflightFailed('configured identity validation failed') from None
    # Authentication and authorization precede ALL external GETs.
    if (identity.tenant_id != environ['UPAOI_TENANT_ID']
            or not REQUIRED_SCOPES.issubset(identity.scopes)):
        raise PreflightFailed('configured identity lacks tenant or read scopes')
    try:
        repo = environ['UPAOI_ALLOWED_REPO']
        page_id = canonical_page_id(environ['UPAOI_ALLOWED_NOTION_PAGE'])
        github = github_reader if github_reader is not None else GithubRepositoryReader(
            {repo}, token_getter=lambda: environ['UPAOI_GITHUB_TOKEN'])
        notion = notion_reader if notion_reader is not None else NotionPageReader(
            {page_id}, token_getter=lambda: environ['UPAOI_NOTION_TOKEN'])
        return verify_source_reads(repo=repo, page_id=page_id,
                                   github_reader=github, notion_reader=notion,
                                   identity=identity,
                                   allowed_tenant=environ['UPAOI_TENANT_ID'])
    except PreflightFailed:
        raise
    except Exception:
        raise PreflightFailed('live source configuration rejected') from None
