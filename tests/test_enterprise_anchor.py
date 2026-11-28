"""Fail-closed verification for independently protected external audit checkpoints."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from nb_orchestrator.enterprise_anchor import ExternalAnchorFile
from nb_orchestrator.enterprise_app import _validate_storage_paths, build_app_from_environment
from nb_orchestrator.enterprise_audit import AuditIntegrityError, AuditJournal
from nb_orchestrator.enterprise_gateway import EnterpriseGateway, TenantPolicy
from nb_orchestrator.enterprise_auth import OidcVerifier
from nb_orchestrator import Agent, Capability, Engine, Registry, Step, Store, Workflow

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient


class AnchoredAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.public.update({"kid": "anchor-test", "alg": "RS256", "use": "sig"})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.anchor_path = base / "external-anchor.json"
        self.audit = AuditJournal(base / "audit.db", signing_key=b"T" * 32)
        self.store = Store(base / "executions.db")
        self.registry = Registry()
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["value"], "properties": {"value": {"type": "string"}}}
        self.registry.register(Capability("local", "read", "1", ("read",), "P0",
                                          schema, schema, scopes=("data:read",)))
        self.calls = []
        def read(args):
            self.calls.append(args)
            return args
        self.workflow = Workflow("test", "1", (Step("read", "local.read", "1", "reader",
                                                      {"value": "allowed"}),))
        engine = Engine(self.registry, self.store,
                        {"reader": Agent("reader", frozenset({"local.read"}))},
                        {"local.read": read})
        self.verifier = OidcVerifier(issuer="https://idp.example.test/", audience="test-upaoi",
                                     jwks={"keys": [self.public]})
        self.gateway = EnterpriseGateway(engine=engine, verifier=self.verifier, audit=self.audit,
                                         catalog={"read": self.workflow},
                                         tenants={"alpha": TenantPolicy(frozenset({"read"}),
                                                                         frozenset({"local.read"}),
                                                                         frozenset({"data:read"}))})

    def tearDown(self):
        self.audit.close()
        self.store.connection.close()
        self.temp.cleanup()

    def token(self):
        import time
        now = int(time.time())
        return jwt.encode({"iss": "https://idp.example.test/", "aud": "test-upaoi",
                           "sub": "alpha-tester", "tenant_id": "alpha", "jti": "id-alpha",
                           "iat": now, "nbf": now - 1, "exp": now + 120,
                           "scope": "data:read"}, self.key, algorithm="RS256",
                          headers={"kid": "anchor-test"})

    def invoke_gateway(self, req):
        return self.gateway.execute(token=self.token(), workflow_key="read",
                                    client_request_id=req)

    def save_anchor(self):
        self.anchor_path.write_text(json.dumps(self.audit.issue_anchor()))
        self.gateway.audit_anchor_reader = ExternalAnchorFile(self.anchor_path)

    def test_external_checkpoint_valid_and_newer_events_accepted(self):
        self.invoke_gateway("first")
        self.save_anchor()
        self.assertEqual(self.invoke_gateway("second")["status"], "COMPLETED")
        self.gateway.check_ready()
        self.assertEqual(len(self.calls), 2)

    def test_deleted_audit_suffix_after_external_checkpoint_fails_closed(self):
        self.invoke_gateway("first")
        self.save_anchor()
        self.audit.connection.execute("DELETE FROM gateway_audit")
        # A totally empty local chain appears valid without an external anchor.
        self.assertTrue(self.audit.verify()["valid"])
        with self.assertRaises(AuditIntegrityError):
            self.gateway.check_ready()
        with self.assertRaises(AuditIntegrityError):
            self.invoke_gateway("second")
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(AuditIntegrityError):
            EnterpriseGateway(engine=self.gateway.engine, verifier=self.verifier,
                              audit=self.audit, catalog=self.gateway.catalog,
                              tenants=self.gateway.tenants,
                              audit_anchor_reader=ExternalAnchorFile(self.anchor_path))

    def test_modified_anchor_denies_readiness_and_new_execution(self):
        self.invoke_gateway("first")
        self.save_anchor()
        obj = json.loads(self.anchor_path.read_text())
        obj["count"] = 0
        self.anchor_path.write_text(json.dumps(obj))
        before = len(self.calls)
        with self.assertRaises(AuditIntegrityError):
            self.gateway.check_ready()
        with self.assertRaises(AuditIntegrityError):
            self.invoke_gateway("another")
        self.assertEqual(len(self.calls), before)

    def test_anchor_removed_or_malformed_returns_generic_error(self):
        self.save_anchor()
        self.anchor_path.unlink()
        with self.assertRaisesRegex(AuditIntegrityError, "checkpoint unavailable") as ctx:
            self.gateway.check_ready()
        self.assertNotIn(str(self.anchor_path), str(ctx.exception))
        self.anchor_path.write_text("{not-json")
        with self.assertRaises(AuditIntegrityError):
            self.gateway.check_ready()

    def test_anchor_response_limit_and_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            ExternalAnchorFile("relative-anchor.json")
        self.anchor_path.write_bytes(b"A" * 4097)
        with self.assertRaises(AuditIntegrityError):
            ExternalAnchorFile(self.anchor_path)()

    def test_http_readiness_reports_503_after_anchor_rollback(self):
        client = TestClient(__import__("nb_orchestrator.enterprise_http", fromlist=["create_app"]).create_app(self.gateway))
        self.invoke_gateway("initial")
        self.save_anchor()
        self.assertEqual(client.get("/health/ready").status_code, 200)
        self.audit.connection.execute("DELETE FROM gateway_audit")
        self.assertEqual(client.get("/health/ready").status_code, 503)
        response = client.post("/v1/runs", json={"workflow_key": "read", "request_id": "rejected"},
                               headers={"Authorization": "Bearer " + self.token()})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(str(self.anchor_path), response.text)
        self.assertEqual(len(self.calls), 1)


class StorageIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_distinct_absolute_paths_permitted(self):
        _validate_storage_paths([str(self.root / x) for x in ("exec.db", "audit.db", "quota.db")])

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            _validate_storage_paths(["./exec.db", str(self.root/"a"), str(self.root/"b")])

    def test_normalized_alias_rejected_before_creation(self):
        a = self.root / "same.db"
        b = self.root / "nested" / ".." / "same.db"
        with self.assertRaises(ValueError):
            _validate_storage_paths([str(a), str(b), str(self.root / "other.db")])

    def test_hardlink_alias_rejected(self):
        a, b = self.root / "a.db", self.root / "b.db"
        a.write_bytes(b"")
        os.link(a, b)
        with self.assertRaises(ValueError):
            _validate_storage_paths([str(a), str(b), str(self.root / "other.db")])

    def test_symlink_alias_rejected(self):
        a, b = self.root / "a.db", self.root / "b.db"
        a.write_bytes(b"")
        b.symlink_to(a)
        with self.assertRaises(ValueError):
            _validate_storage_paths([str(a), str(b), str(self.root / "other.db")])

    def test_invalid_external_anchor_policy_rejected_before_app_start(self):
        root = self.root
        # Complete required configuration except the policy setting under test.
        cfg = {"UPAOI_OIDC_ISSUER": "https://issuer.example/",
               "UPAOI_OIDC_AUDIENCE": "pilot",
               "UPAOI_OIDC_JWKS_JSON": "{}",
               "UPAOI_AUDIT_KEY_HEX": (b"M"*32).hex(),
               "UPAOI_TENANT_ID": "test-tenant",
               "UPAOI_ALLOWED_REPO": "NeuralBlitz/UPAOI",
               "UPAOI_ALLOWED_NOTION_PAGE": "41325ca4-47c1-81ac-82ae-e167d8fe80fd",
               "UPAOI_EXECUTION_DB": str(root / "exec.db"),
               "UPAOI_AUDIT_DB": str(root / "audit.db"),
               "UPAOI_ADMISSION_DB": str(root / "admission.db"),
               "UPAOI_REQUIRE_EXTERNAL_AUDIT_ANCHOR": "1"}
        with self.assertRaisesRegex(RuntimeError, "checkpoint required"):
            build_app_from_environment(cfg)
        cfg["UPAOI_REQUIRE_EXTERNAL_AUDIT_ANCHOR"] = "maybe"
        with self.assertRaisesRegex(ValueError, "invalid audit anchor policy"):
            build_app_from_environment(cfg)

if __name__ == "__main__":
    unittest.main()
