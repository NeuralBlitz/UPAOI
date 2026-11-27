# UPAOI MVP v0.2.0 — validation checkpoint

Date: 2026-11-22 (America/Chicago)

## Reproducible commands

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m unittest discover -s tests -v
upaoi demo --db local-demo.sqlite
upaoi sources --fixture --repo NeuralBlitz/AgentOS --page-id 41325ca4-47c1-81ac-82ae-e167d8fe80fd --db fixture-sources.sqlite
upaoi health --inventory data/plugin-health-2026-11-22.json
```

## Recorded results in local execution container

- **31 / 31 unit tests passed**; all use mock provider transports or local adapters rather than live connector credentials.
- **Local demo:** COMPLETED, 3 steps, 9 ledger events.
- **Synthetic GitHub+Notion source workflow:** COMPLETED, 3 steps, 9 ledger events. Marked `mode: synthetic_fixture`.
- **Historical plugin inventory:** 88 records loaded (73 read-only responses, 5 blocked, 10 untested). Not proof of complete feature health.
- **Editable install:** succeeded with an already-installed build backend and dependencies; build-isolated clean installation was not tested.

## Negative tests

- Unauthorized GitHub/Notion identifiers rejected before HTTP call.
- Malformed repository path rejected.
- Incorrect provider identity rejected.
- Missing Notion token rejected.
- Provider output is projected into a strict response schema; prompt-like text remains data.
- Cached response cannot be returned without **current** capability grants and scopes.
- Started-but-incomplete write is quarantined even if process crash prevented a failure event.
- Existing tests still cover request-ID collision, DAG cycles, declared references, schema drift, output validation, resumed reads, and idempotent completed replays.

## Explicit non-claims

- Live Github/Notion REST integration calls have **not** been performed by the standalone Python program. Connected ChatGPT GitHub/Notion plugins were inspected separately, not called by the Python runtime.
- GitHub repository `NeuralBlitz/UPAOI` is **not created**; browser login required and current GitHub plugin exposes no repository-create tool.
- GitHub Actions CI configuration is present but **not executed** until pushed to a repository.
- No server, queue, trust-broker, production API, deployment, independent claim verification, distributed transaction or agent LLM planner was constructed.
- Additional security review and real-provider integration tests are mandatory before production.
