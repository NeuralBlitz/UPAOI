"""Optional FastAPI entrypoint for the enterprise read-only pilot.

Deploy only behind configured TLS ingress, request rate limits and trusted
OIDC issuer key lifecycle management. No OAuth flows or tokens are logged.
"""
from __future__ import annotations

import json
from fastapi import Request

from .enterprise_auth import AuthenticationDenied
from .enterprise_audit import AuditIntegrityError
from .enterprise_gateway import AuthorizationDenied, EnterpriseGateway
from .enterprise_quota import AdmissionQuotaExceeded


def create_app(gateway: EnterpriseGateway, *, max_body_bytes: int = 4096):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    if not 256 <= max_body_bytes <= 65536:
        raise ValueError("HTTP body limit must be bounded")
    app = FastAPI(title="UPAOI Read-only Enterprise Pilot", version="0.4.1", docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def do_not_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health/live")
    async def liveness():
        return {"status": "up"}

    @app.get("/health/ready")
    async def readiness():
        try:
            await run_in_threadpool(gateway.check_ready)
        except Exception:
            raise HTTPException(status_code=503, detail="service not ready") from None
        return {"status": "ready"}

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
            result = await run_in_threadpool(
                gateway.execute, token=bearer[7:], workflow_key=document["workflow_key"],
                client_request_id=document["request_id"])
        except AuthenticationDenied:
            raise HTTPException(status_code=401, detail="invalid bearer token") from None
        except AuthorizationDenied:
            raise HTTPException(status_code=403, detail="not authorized") from None
        except AdmissionQuotaExceeded as exc:
            raise HTTPException(status_code=429, detail="request admission limit reached",
                                headers={"Retry-After": str(exc.retry_after_seconds)}) from None
        except AuditIntegrityError:
            # Audit rollback/missing checkpoints disable admission; no provider call.
            raise HTTPException(status_code=503, detail="service audit integrity unavailable") from None
        # A blocked run is not a successful execution. Avoid 200 on policy failures.
        status_code = {"COMPLETED": 200, "BLOCKED": 409, "FAILED": 424}[result["status"]]
        return JSONResponse(status_code=status_code, content=result)

    return app
