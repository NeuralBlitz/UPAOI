"""Optional FastAPI entrypoint for the enterprise read-only pilot.

Deploy only behind configured TLS ingress, request rate limits and trusted
OIDC issuer key lifecycle management. No OAuth flows or tokens are logged.
"""
from __future__ import annotations

import json
from fastapi import Request

from .enterprise_auth import AuthenticationDenied
from .enterprise_gateway import AuthorizationDenied, EnterpriseGateway


def create_app(gateway: EnterpriseGateway, *, max_body_bytes: int = 4096):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    if not 256 <= max_body_bytes <= 65536:
        raise ValueError("HTTP body limit must be bounded")
    app = FastAPI(title="UPAOI Read-only Enterprise Pilot", version="0.4.0", docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def do_not_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health/live")
    async def liveness():
        return {"status": "up"}

    @app.post("/v1/runs")
    async def run(request: Request):
        # Reject oversized bodies while streaming, before buffering entire payload.
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > max_body_bytes:
                raise HTTPException(status_code=413, detail="request body too large")
            chunks.append(chunk)
        try:
            if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                raise ValueError("bad content type")
            document = json.loads(b"".join(chunks))
            if (not isinstance(document, dict) or set(document) != {"workflow_key", "request_id"}
                    or not all(isinstance(v, str) for v in document.values())):
                raise ValueError("unexpected request payload")
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="invalid request payload") from None
        # A duplicate Authorization header creates ambiguous credentials.
        if sum(k.lower() == b"authorization" for k, _ in request.scope.get("headers", [])) != 1:
            raise HTTPException(status_code=401, detail="missing or ambiguous bearer credential")
        bearer = request.headers.get("authorization", "")
        if not bearer.startswith("Bearer ") or len(bearer) > 8200:
            raise HTTPException(status_code=401, detail="missing or invalid bearer token")
        try:
            result = gateway.execute(token=bearer[7:], workflow_key=document["workflow_key"],
                                     client_request_id=document["request_id"])
        except AuthenticationDenied:
            raise HTTPException(status_code=401, detail="invalid bearer token") from None
        except AuthorizationDenied:
            raise HTTPException(status_code=403, detail="not authorized") from None
        # A blocked run is not a successful execution. Avoid 200 on policy failures.
        status_code = {"COMPLETED": 200, "BLOCKED": 409, "FAILED": 424}[result["status"]]
        return JSONResponse(status_code=status_code, content=result)

    return app
