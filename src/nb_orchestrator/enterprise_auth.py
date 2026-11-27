"""Offline-key, asymmetric OIDC token verification for the read-only gateway.

No HTTP fetching or trust-on-first-use: an operator must obtain the issuer's
public JWKS through a trusted configuration channel and rotate it deliberately.
Never accept an algorithm, issuer, audience or tenant from an untrusted request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class AuthenticationDenied(Exception):
    """An authentication failure with a deliberately non-revealing message."""


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    token_id: str
    issued_at: int
    expires_at: int


class OidcVerifier:
    def __init__(self, *, issuer: str, audience: str, jwks: dict[str, Any],
                 tenant_claim: str = "tenant_id", max_token_lifetime: int = 900,
                 leeway_seconds: int = 30) -> None:
        import jwt
        if not issuer.startswith("https://") or not audience or not tenant_claim:
            raise ValueError("OIDC issuer must be HTTPS with a configured audience and tenant claim")
        if not (0 <= leeway_seconds <= 60 and 30 <= max_token_lifetime <= 3600):
            raise ValueError("OIDC token validity bounds outside security policy")
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise ValueError("trusted public JWKS required")
        keys = {}
        for key in jwks["keys"]:
            if not isinstance(key, dict):
                raise ValueError("invalid public key")
            kid = key.get("kid")
            if (not isinstance(kid, str) or not kid or len(kid) > 128 or kid in keys
                    or key.get("kty") != "RSA" or key.get("alg") != "RS256"
                    or key.get("use", "sig") != "sig"
                    or any(private in key for private in ("d", "p", "q", "dp", "dq", "qi"))):
                raise ValueError("only unique RSA public signing keys with RS256 are permitted")
            try:
                keys[kid] = jwt.PyJWK.from_dict(key, algorithm="RS256").key
            except Exception as exc:
                raise ValueError("invalid public signing key") from exc
        if not keys:
            raise ValueError("at least one public signing key required")
        self.issuer, self.audience, self.tenant_claim = issuer, audience, tenant_claim
        self.max_token_lifetime, self.leeway_seconds = max_token_lifetime, leeway_seconds
        self._keys = keys

    def verify(self, token: str) -> VerifiedIdentity:
        import jwt
        if not isinstance(token, str) or len(token) > 8192 or token.count(".") != 2:
            raise AuthenticationDenied("invalid bearer credential")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or header.get("kid") not in self._keys:
                raise AuthenticationDenied("invalid bearer credential")
            claims = jwt.decode(
                token, self._keys[header["kid"]], algorithms=["RS256"],
                issuer=self.issuer, audience=self.audience,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nbf", "jti", self.tenant_claim]},
                leeway=self.leeway_seconds,
            )
            subject, tenant, jti = claims["sub"], claims[self.tenant_claim], claims["jti"]
            issued, expires, not_before = claims["iat"], claims["exp"], claims["nbf"]
            if (not all(isinstance(v, str) and v.strip() and len(v) <= 200
                                and all(ord(ch) >= 32 for ch in v) for v in (subject, tenant, jti))
                    or not all(type(v) is int for v in (issued, expires, not_before))
                    or expires <= issued or expires - issued > self.max_token_lifetime
                    or not_before > expires or issued > int(time.time()) + self.leeway_seconds):
                raise AuthenticationDenied("invalid bearer credential")
            raw_scope = claims.get("scope", "")
            if not isinstance(raw_scope, str) or len(raw_scope) > 4096:
                raise AuthenticationDenied("invalid bearer credential")
            scopes = frozenset(raw_scope.split())
            if not all(0 < len(scope) < 150 for scope in scopes):
                raise AuthenticationDenied("invalid bearer credential")
            return VerifiedIdentity(self.issuer, subject, tenant, scopes, jti, issued, expires)
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, AuthenticationDenied) as exc:
            raise AuthenticationDenied("invalid bearer credential") from None
