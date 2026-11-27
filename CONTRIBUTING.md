# Contributing to UPAOI

UPAOI is an experimental orchestration engine. It is **not approved for production actions**.

1. Make changes on a branch and submit a pull request. Do not push directly to `main` after the initial bootstrap.
2. Run `python -m pip install -e .` and `python -m unittest discover -s tests -v`.
3. Preserve the fail-closed policy gate. Never allow untrusted documents or generated model text to authorize new capabilities.
4. Do not introduce provider write adapters without a verified authorization gateway, idempotency/reconciliation, and regression tests.
5. Describe source provenance, test evidence, known limitations, and security implications in pull requests.
6. Use minimal permissions in CI and never commit credentials, tokens, or real confidential provider payloads.
