"""Negative-path, identity, tenant, HTTP and audit tests with throwaway RSA keys."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest.mock import Mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from nb_orchestrator import Agent, Capability, Engine, Registry, Step, Store, Workflow
from nb_orchestrator.enterprise_auth import AuthenticationDenied, OidcVerifier
from nb_orchestrator.enterprise_audit import AuditIntegrityError, AuditJournal
from nb_orchestrator.enterprise_gateway import AuthorizationDenied, EnterpriseGateway, TenantPolicy
from nb_orchestrator.enterprise_http import create_app
from nb_orchestrator.enterprise_quota import AdmissionQuotaExceeded, QuotaLedger

ISSUER = "https://oidc.test.example/"
AUDIENCE = "upaoi-enterprise-pilot"
SCHEMA_IN = {"type": "object", "properties": {"message": {"type": "string"}},
             "required": ["message"], "additionalProperties": False}
SCHEMA_OUT = {"type": "object", "properties": {"echo": {"type": "string"}},
              "required": ["echo"], "additionalProperties": False}


class EnterpriseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private_key.public_key()))
        cls.public_jwk.update({"kid": "enterprise-test-kid", "alg": "RS256", "use": "sig"})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "execution.db")
        self.audit = AuditJournal(Path(self.temp.name) / "audit.db", signing_key=b"A" * 32)
        self.verifier = OidcVerifier(issuer=ISSUER, audience=AUDIENCE, jwks={"keys": [self.public_jwk]})
        self.registry = Registry()
        self.registry.register(Capability("local", "read", "1", ("read",), "P0", SCHEMA_IN, SCHEMA_OUT,
                                          scopes=("data:read",)))
        self.calls = []
        def read(args):
            self.calls.append(args)
            return {"echo": args["message"]}
        self.workflow = Workflow("sample", "1", (Step("read", "local.read", "1", "agent",
                                                      {"message": "allowed"}),))
        engine = Engine(self.registry, self.store, {"agent": Agent("agent", frozenset({"local.read"}))},
                        {"local.read": read})
        policies = {"tenant-A": TenantPolicy(frozenset({"read-sample"}), frozenset({"local.read"}),
                                               frozenset({"data:read"})),
                    "tenant-B": TenantPolicy(frozenset({"read-sample"}), frozenset({"local.read"}),
                                               frozenset({"data:read"}))}
        self.gateway = EnterpriseGateway(engine=engine, verifier=self.verifier, audit=self.audit,
                                         catalog={"read-sample": self.workflow}, tenants=policies)

    def tearDown(self):
        self.store.connection.close()
        self.audit.close()
        self.temp.cleanup()

    def token(self, *, subject="alice", tenant="tenant-A", scope="data:read", **overrides):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": subject, "tenant_id": tenant,
                  "iat": now, "nbf": now - 1, "exp": now + 300, "jti": "t-123", "scope": scope}
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "enterprise-test-kid"})

    def run_request(self, token=None, req="request-1"):
        return self.gateway.execute(token=token or self.token(), workflow_key="read-sample",
                                    client_request_id=req)

    def test_authorized_run_and_cached_duplicate(self):
        self.assertEqual(self.run_request()["status"], "COMPLETED")
        self.assertEqual(self.run_request()["outputs"]["read"]["echo"], "allowed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.audit.verify()["count"], 4)
        raw = repr(self.audit.connection.execute("SELECT attributes FROM gateway_audit").fetchall())
        self.assertNotIn("data:read", raw)
        self.assertNotIn("tenant-A", raw)
        self.assertNotIn("allowed", raw)

    def test_request_ids_isolated_across_tenants(self):
        self.run_request(token=self.token(tenant="tenant-A"))
        self.run_request(token=self.token(tenant="tenant-B"))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0], 2)

    def test_request_ids_isolated_across_subjects(self):
        self.run_request(token=self.token(subject="alice"))
        self.run_request(token=self.token(subject="bob"))
        self.assertEqual(len(self.calls), 2)

    def test_replay_with_token_missing_current_scope_is_denied(self):
        self.run_request(req="replay-rights")
        with self.assertRaises(AuthorizationDenied):
            self.run_request(token=self.token(scope="profile:read"), req="replay-rights")
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_http_runs_share_locked_sqlite_safely(self):
        token = self.token()
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self.gateway.execute, token=token,
                         workflow_key="read-sample", client_request_id=f"parallel-{i}")
                       for i in range(24)]
            results = [future.result() for future in futures]
        self.assertEqual({result["status"] for result in results}, {"COMPLETED"})
        self.assertEqual(len(self.calls), 24)
        self.assertEqual(self.audit.verify()["count"], 48)

    def test_tenant_acl_denies_unknown_tenant_without_adapter(self):
        with self.assertRaises(AuthorizationDenied):
            self.run_request(token=self.token(tenant="tenant-C"))
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(self.audit.verify()["count"], 0)

    def test_token_scope_denied(self):
        with self.assertRaises(AuthorizationDenied):
            self.run_request(token=self.token(scope="profile:read"))
        self.assertFalse(self.calls)

    def test_denied_workflow_and_invalid_request_id(self):
        with self.assertRaises(AuthorizationDenied):
            self.gateway.execute(token=self.token(), workflow_key="not-registered", client_request_id="x")
        with self.assertRaises(AuthorizationDenied):
            self.run_request(req="bad identifier / unauthorized")

    def test_reject_invalid_signature(self):
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "tenant_id": "tenant-A",
                  "iat": now, "nbf": now, "exp": now+300, "jti": "j", "scope": "data:read"}
        forged = jwt.encode(claims, wrong_key, algorithm="RS256", headers={"kid": "enterprise-test-kid"})
        with self.assertRaises(AuthenticationDenied):
            self.run_request(token=forged)

    def test_invalid_issuer_audience_expiry_future_and_missing_claim(self):
        invalid_claims = [
            {"iss": "https://attacker.example/"},
            {"aud": "other-service"},
            {"exp": int(time.time()) - 600},
            {"nbf": int(time.time()) + 600},
            {"iat": int(time.time()) + 600},
            {"exp": int(time.time()) + 3601},
            {"tenant_id": ""},
            {"jti": ""},
            {"scope": 23},
        ]
        for claims in invalid_claims:
            with self.subTest(claims=claims), self.assertRaises(AuthenticationDenied):
                self.run_request(token=self.token(**claims))
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "tenant_id": "tenant-A",
                  "iat": int(time.time()), "nbf": int(time.time()), "exp": int(time.time())+300}
        with self.assertRaises(AuthenticationDenied):
            self.run_request(token=jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid":"enterprise-test-kid"}))

    def test_unknown_kid_and_none_algorithm(self):
        t = self.token()
        with self.assertRaises(AuthenticationDenied):
            self.run_request(token=jwt.encode(jwt.decode(t, options={"verify_signature":False}),
                                                  self.private_key, algorithm="RS256", headers={"kid":"unrecognized"}))
        with self.assertRaises(AuthenticationDenied):
            self.run_request(token=jwt.encode(jwt.decode(t, options={"verify_signature":False}),
                                                  key="", algorithm="none", headers={"kid":"enterprise-test-kid"}))

    def test_bad_jwks_rejected(self):
        bad = {**self.public_jwk, "d": "private"}
        with self.assertRaises(ValueError):
            OidcVerifier(issuer=ISSUER, audience=AUDIENCE, jwks={"keys": [bad]})
        with self.assertRaises(ValueError):
            OidcVerifier(issuer=ISSUER, audience=AUDIENCE, jwks={"keys": [self.public_jwk, self.public_jwk]})
        with self.assertRaises(ValueError):
            OidcVerifier(issuer="http://insecure", audience=AUDIENCE, jwks={"keys": [self.public_jwk]})

    def test_deployable_factory_fails_closed_without_configuration(self):
        from nb_orchestrator.enterprise_app import build_app_from_environment
        with self.assertRaises(RuntimeError):
            build_app_from_environment({})

    def test_deployable_factory_uses_explicit_tenant_and_source_policy(self):
        from nb_orchestrator.enterprise_app import build_app_from_environment
        config={
            "UPAOI_OIDC_ISSUER": ISSUER, "UPAOI_OIDC_AUDIENCE": AUDIENCE,
            "UPAOI_OIDC_JWKS_JSON": json.dumps({"keys":[self.public_jwk]}),
            "UPAOI_AUDIT_KEY_HEX": (b"Z"*32).hex(),
            "UPAOI_TENANT_ID": "tenant-A", "UPAOI_ALLOWED_REPO": "NeuralBlitz/UPAOI",
            "UPAOI_ALLOWED_NOTION_PAGE": "41325ca4-47c1-81ac-82ae-e167d8fe80fd",
            "UPAOI_EXECUTION_DB": str(Path(self.temp.name)/"configured-execution.db"),
            "UPAOI_AUDIT_DB": str(Path(self.temp.name)/"configured-audit.db"),
            "UPAOI_ADMISSION_DB": str(Path(self.temp.name)/"configured-admission.db"),
        }
        app=build_app_from_environment(config)
        client=TestClient(app)
        self.assertEqual(client.get("/health/live").status_code,200)
        self.assertEqual(client.post("/v1/runs",json={"request_id":"r", "workflow_key":"source-inventory"}).status_code,401)
        # The independently configured source workflow does not accept forged tenant overrides.
        self.assertEqual(client.post("/v1/runs",headers={"Authorization":"Bearer "+self.token()},
                          json={"request_id":"r", "workflow_key":"source-inventory", "tenant_id":"tenant-A"}).status_code,400)

    def test_reject_all_write_workflows_even_with_existing_engine(self):
        cap = Capability("local", "write", "1", ("write",), "P1", SCHEMA_IN, SCHEMA_OUT)
        self.registry.register(cap)
        workflow = Workflow("write", "1", (Step("modify", "local.write", "1", "agent", {"message": "x"}),))
        with self.assertRaises(ValueError):
            EnterpriseGateway(engine=self.gateway.engine, verifier=self.verifier, audit=self.audit,
                              catalog={"unsafe": workflow}, tenants=self.gateway.tenants)

    def test_bounded_step_budget(self):
        many = Workflow("many", "1", tuple(Step(f"s{i}", "local.read", "1", "agent", {"message":"ok"})
                                            for i in range(17)))
        with self.assertRaises(ValueError):
            EnterpriseGateway(engine=self.gateway.engine, verifier=self.verifier, audit=self.audit,
                              catalog={"many":many}, tenants=self.gateway.tenants)

    def test_audit_rejects_corrupted_row(self):
        self.run_request()
        self.audit.connection.execute("UPDATE gateway_audit SET event_type='RUN_FAILED' WHERE seq=1")
        with self.assertRaises(AuditIntegrityError):
            self.audit.verify()

    def test_audit_rejects_deleted_interior_row(self):
        self.run_request()
        self.audit.connection.execute("DELETE FROM gateway_audit WHERE seq=1")
        with self.assertRaises(AuditIntegrityError):
            self.audit.verify()

    def test_audit_receipt_secret_not_persisted(self):
        self.run_request(token=self.token(jti="VERY_PRIVATE_JTI_VALUE"))
        data=repr(self.audit.connection.execute("SELECT * FROM gateway_audit").fetchall())
        self.assertNotIn("VERY_PRIVATE_JTI_VALUE", data)

    def test_audit_unavailable_blocks_adapter(self):
        self.audit.close()
        self.audit = AuditJournal(Path(self.temp.name)/"audit2.db", signing_key=b"B"*32)
        self.gateway.audit = Mock()
        self.gateway.audit.append.side_effect=sqlite3.OperationalError("audit unavailable")
        with self.assertRaises(sqlite3.OperationalError):
            self.run_request()
        self.assertFalse(self.calls)

    def test_http_success_and_health(self):
        client=TestClient(create_app(self.gateway))
        self.assertEqual(client.get("/health/live").json(), {"status":"up"})
        r=client.post("/v1/runs", headers={"Authorization":"Bearer "+self.token()},
                      json={"request_id":"http-1", "workflow_key":"read-sample"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["status"],"COMPLETED")
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_http_unauthorized(self):
        client=TestClient(create_app(self.gateway))
        data={"request_id":"http-1", "workflow_key":"read-sample"}
        self.assertEqual(client.post("/v1/runs",json=data).status_code,401)
        self.assertEqual(client.post("/v1/runs",json=data,headers={"Authorization":"Bearer forged"}).status_code,401)
        self.assertFalse(self.calls)

    def test_http_acl_rejection(self):
        client=TestClient(create_app(self.gateway))
        r=client.post("/v1/runs",json={"request_id":"x","workflow_key":"read-sample"},
                      headers={"Authorization":"Bearer "+self.token(tenant="tenant-unknown")})
        self.assertEqual(r.status_code,403)

    def test_http_rejects_forged_identity_fields(self):
        client=TestClient(create_app(self.gateway))
        data={"request_id":"x", "workflow_key":"read-sample", "principal_id":"admin",
              "approvals":["everything"]}
        r=client.post("/v1/runs",json=data,headers={"Authorization":"Bearer "+self.token()})
        self.assertEqual(r.status_code,400)
        self.assertFalse(self.calls)

    def test_http_rejects_ambiguous_auth_headers(self):
        client=TestClient(create_app(self.gateway))
        from httpx import Headers
        r=client.post("/v1/runs",json={"request_id":"x", "workflow_key":"read-sample"},
                      headers=[("Authorization", "Bearer "+self.token()),
                               ("Authorization", "Bearer "+self.token())])
        self.assertEqual(r.status_code, 401)
        self.assertFalse(self.calls)

    def test_http_rejects_body_limit_and_type(self):
        client=TestClient(create_app(self.gateway))
        header={"Authorization":"Bearer "+self.token()}
        self.assertEqual(client.post("/v1/runs",headers=header,
                                     content=b"x"*5000).status_code,413)
        self.assertEqual(client.post("/v1/runs",headers=header,
                                     content="not json").status_code,400)

    def test_no_public_openapi_and_docs_routes(self):
        client=TestClient(create_app(self.gateway))
        self.assertEqual(client.get("/openapi.json").status_code,404)
        self.assertEqual(client.get("/docs").status_code,404)

    def test_rate_limit_is_429_and_preserves_safe_admission(self):
        self.gateway.quota = QuotaLedger(Path(self.temp.name)/"quota.db",
                                         tenant_limit=2, principal_limit=1)
        client = TestClient(create_app(self.gateway))
        headers = {"Authorization": "Bearer " + self.token()}
        self.assertEqual(client.post("/v1/runs", headers=headers,
                                    json={"request_id":"first","workflow_key":"read-sample"}).status_code, 200)
        second = client.post("/v1/runs", headers=headers,
                             json={"request_id":"second","workflow_key":"read-sample"})
        self.assertEqual(second.status_code, 429)
        self.assertTrue(0 < int(second.headers["retry-after"]) <= 60)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.audit.verify()["count"], 3)
        self.assertNotIn("tenant-A", repr(self.gateway.quota.connection.execute(
            "SELECT * FROM admission_quota").fetchall()))
        self.gateway.quota.close()

    def test_cached_replay_consumes_quota(self):
        self.gateway.quota = QuotaLedger(Path(self.temp.name)/"quota.db",
                                         tenant_limit=2, principal_limit=1)
        self.run_request(req="replay")
        with self.assertRaises(AdmissionQuotaExceeded):
            self.run_request(req="replay")
        self.assertEqual(len(self.calls),1)
        self.gateway.quota.close()

    def test_workflow_request_collision_returns_409_without_leaking_output(self):
        self.run_request(req="shared")
        another = Workflow("other-spec", "1", self.workflow.steps)
        catalog = {"read-sample": self.workflow, "other": another}
        policy = TenantPolicy(frozenset(catalog), frozenset({"local.read"}),
                              frozenset({"data:read"}))
        self.gateway.catalog = catalog
        self.gateway.tenants["tenant-A"] = policy
        client = TestClient(create_app(self.gateway))
        r = client.post("/v1/runs", headers={"Authorization":"Bearer "+self.token()},
                        json={"request_id":"shared","workflow_key":"other"})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(r.json()["outputs"], {})
        self.assertEqual(len(self.calls),1)

    def test_readiness_healthy_and_corrupt_chain(self):
        client = TestClient(create_app(self.gateway))
        self.assertEqual(client.get("/health/ready").status_code,200)
        self.run_request()
        self.audit.connection.execute("UPDATE gateway_audit SET mac=? WHERE seq=1", ('0'*64,))
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('mac', response.text)

    def test_readiness_fails_if_quota_ledger_closed(self):
        self.gateway.quota = QuotaLedger(Path(self.temp.name)/"quota.db")
        self.gateway.quota.close()
        client = TestClient(create_app(self.gateway))
        self.assertEqual(client.get("/health/ready").status_code,503)

    def test_security_headers_are_not_cacheable(self):
        client = TestClient(create_app(self.gateway))
        response=client.get("/health/ready")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_audit_anchor_detects_rollback(self):
        self.run_request(req="anchor-1")
        anchor = self.audit.issue_anchor()
        self.assertEqual(self.audit.verify_anchor(anchor)["anchored_count"], 2)
        self.run_request(req="anchor-2")
        self.assertEqual(self.audit.verify_anchor(anchor)["count"], 4)
        self.audit.connection.execute("DELETE FROM gateway_audit WHERE seq > 1")
        with self.assertRaises(AuditIntegrityError):
            self.audit.verify_anchor(anchor)

    def test_audit_anchor_rejects_tamper_and_wrong_key(self):
        self.run_request()
        anchor=self.audit.issue_anchor()
        forged={**anchor,"tip_mac":"0"*64}
        with self.assertRaises(AuditIntegrityError):
            self.audit.verify_anchor(forged)
        foreign=AuditJournal(Path(self.temp.name)/"other-audit.db", signing_key=b'B'*32)
        try:
            with self.assertRaises(AuditIntegrityError):
                foreign.verify_anchor(anchor)
        finally:
            foreign.close()

    def test_invalid_config_rejects_missing_admission_file(self):
        from nb_orchestrator.enterprise_app import build_app_from_environment
        config={"UPAOI_OIDC_ISSUER":ISSUER,"UPAOI_OIDC_AUDIENCE":AUDIENCE,
                "UPAOI_OIDC_JWKS_JSON":json.dumps({"keys":[self.public_jwk]}),
                "UPAOI_AUDIT_KEY_HEX": (b'Z'*32).hex(),"UPAOI_TENANT_ID":"tenant-A",
                "UPAOI_ALLOWED_REPO":"NeuralBlitz/UPAOI",
                "UPAOI_ALLOWED_NOTION_PAGE":"41325ca4-47c1-81ac-82ae-e167d8fe80fd",
                "UPAOI_EXECUTION_DB":str(Path(self.temp.name)/"exec.db"),
                "UPAOI_AUDIT_DB":str(Path(self.temp.name)/"audit-config.db")}
        with self.assertRaises(RuntimeError):
            build_app_from_environment(config)
        config["UPAOI_ADMISSION_DB"] = config["UPAOI_AUDIT_DB"]
        with self.assertRaises(ValueError):
            build_app_from_environment(config)


if __name__ == "__main__":
    unittest.main()
