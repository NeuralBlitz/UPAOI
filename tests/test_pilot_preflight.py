"""Offline-only M3 integration preflight tests: never call provider networks."""
from __future__ import annotations

import json
import time
import unittest
from unittest.mock import Mock
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from nb_orchestrator.enterprise_auth import VerifiedIdentity
from nb_orchestrator.pilot_preflight import (PreflightFailed, run_fixture_preflight,
                                              run_configured_preflight, verify_source_reads)
from nb_orchestrator.fixtures import fixture_readers

REPO = 'NeuralBlitz/UPAOI'
PAGE = '41325ca4-47c1-81ac-82ae-e167d8fe80fd'
ISSUER = 'https://test-oidc.example/'
AUDIENCE = 'upaoi-internal-alpha'


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private_key.public_key()))
        cls.pub.update({'kid':'test-kid', 'alg':'RS256', 'use':'sig'})

    def setUp(self):
        now=int(time.time())
        self.claims={'iss':ISSUER,'aud':AUDIENCE,'sub':'test-operator',
                     'tenant_id':'tenant-A', 'jti':'identifier-SECRET',
                     'iat':now,'nbf':now-1,'exp':now+240,
                     'scope':'github:repository:read notion:page:read'}
        self.config={'UPAOI_OIDC_ISSUER':ISSUER,'UPAOI_OIDC_AUDIENCE':AUDIENCE,
                     'UPAOI_OIDC_JWKS_JSON':json.dumps({'keys':[self.pub]}),
                     'UPAOI_OIDC_TEST_ACCESS_TOKEN':self.token(),
                     'UPAOI_TENANT_ID':'tenant-A',
                     'UPAOI_ALLOWED_REPO':REPO, 'UPAOI_ALLOWED_NOTION_PAGE':PAGE,
                     'UPAOI_GITHUB_TOKEN':'GH_SECRET_DO_NOT_LOG',
                     'UPAOI_NOTION_TOKEN':'NOTION_SECRET_DO_NOT_LOG'}
        self.repo,self.page=fixture_readers(REPO,PAGE)

    def token(self, **overrides):
        return jwt.encode({**self.claims,**overrides},self.private_key,
                          algorithm='RS256',headers={'kid':'test-kid'})

    def fixture(self):
        return run_fixture_preflight(REPO,PAGE)

    def configured(self,config=None,**kwargs):
        return run_configured_preflight(config if config is not None else self.config,
                                        github_reader=kwargs.get('github_reader',self.repo),
                                        notion_reader=kwargs.get('notion_reader',self.page))

    def test_fixture_is_unambiguously_synthetic(self):
        r=self.fixture()
        self.assertEqual(r['status'],'SIMULATED_ONLY')
        self.assertFalse(r['claims_verified'])
        self.assertFalse(r['release_approved'])

    def test_no_source_body_or_token_claims_in_receipt(self):
        r=self.configured()
        data=json.dumps(r,sort_keys=True)
        self.assertEqual(r['status'],'READ_ONLY_SOURCES_REACHED')
        for secret in ('NOTION_SECRET_DO_NOT_LOG','GH_SECRET_DO_NOT_LOG',
                       'test-operator','tenant-A','identifier-SECRET',
                       'SYNTHETIC TEST FIXTURE'):
            self.assertNotIn(secret,data)
        self.assertFalse(r['content_claims_independently_verified'])

    def test_missing_credential_fails_before_any_read(self):
        repo=Mock(side_effect=AssertionError('should not call provider'))
        env={**self.config,'UPAOI_GITHUB_TOKEN':''}
        with self.assertRaises(PreflightFailed):
            self.configured(env,github_reader=repo)
        repo.assert_not_called()

    def test_wrong_tenant_fails_before_reads(self):
        repo=Mock(side_effect=AssertionError('should not call provider'))
        with self.assertRaises(PreflightFailed):
            self.configured({**self.config,'UPAOI_TENANT_ID':'tenant-B'},github_reader=repo)
        repo.assert_not_called()

    def test_missing_read_scope_fails_before_reads(self):
        repo=Mock(side_effect=AssertionError('should not call provider'))
        with self.assertRaises(PreflightFailed):
            self.configured({**self.config, 'UPAOI_OIDC_TEST_ACCESS_TOKEN':self.token(scope='github:repository:read')},github_reader=repo)
        repo.assert_not_called()

    def test_wrong_signature_fails_before_reads(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        bad=jwt.encode(self.claims,key,algorithm='RS256',headers={'kid':'test-kid'})
        repo=Mock(side_effect=AssertionError('should not call provider'))
        with self.assertRaises(PreflightFailed):
            self.configured({**self.config,'UPAOI_OIDC_TEST_ACCESS_TOKEN':bad},github_reader=repo)
        repo.assert_not_called()

    def test_provider_identity_mismatch_fails_closed(self):
        def mismatch(args):
            r=self.repo(args)
            return {**r,'full_name':'other/repo'}
        with self.assertRaises(PreflightFailed) as ctx:
            self.configured(github_reader=mismatch)
        self.assertNotIn('other/repo',str(ctx.exception))

    def test_provider_exception_is_redacted(self):
        def fail(args):
            raise RuntimeError('DO_NOT_SHOW_SECRET_123')
        with self.assertRaises(PreflightFailed) as ctx:
            self.configured(notion_reader=fail)
        self.assertNotIn('DO_NOT_SHOW_SECRET_123',str(ctx.exception))

    def test_invalid_fixture_sources_rejected_without_network(self):
        for repo,page in [('missing-slash',PAGE),(REPO,'not-a-uuid')]:
            with self.subTest(repo=repo,page=page),self.assertRaises(PreflightFailed):
                run_fixture_preflight(repo,page)

    def test_identity_required_if_tenant_bound(self):
        with self.assertRaises(PreflightFailed):
            verify_source_reads(repo=REPO,page_id=PAGE,github_reader=self.repo,
                                notion_reader=self.page,allowed_tenant='tenant-A')

    def test_claims_wrong_audience_rejected(self):
        with self.assertRaises(PreflightFailed):
            self.configured({**self.config,'UPAOI_OIDC_TEST_ACCESS_TOKEN':self.token(aud='forged')})

    def test_expired_token_rejected(self):
        now=int(time.time())
        with self.assertRaises(PreflightFailed):
            self.configured({**self.config,'UPAOI_OIDC_TEST_ACCESS_TOKEN':self.token(iat=now-600,nbf=now-601,exp=now-200)})


if __name__=='__main__':
    unittest.main()
