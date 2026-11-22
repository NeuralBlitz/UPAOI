# Dedicated GitHub repository and delivery workflow

**Repository:** [`NeuralBlitz/UPAOI`](https://github.com/NeuralBlitz/UPAOI) — private, independent from AgentOS, NBOS, Nexus and Agent-Gateway.

## Initial import

The repository was created by the account holder on 2026-11-22, with an initial `main` README. The v0.2.0 Python source, tests, documentation and CI configuration are staged separately on `feat/bootstrap-upaoi-v0.2.0` for code review. Do not merge until the PR checks run and maintainers review the changes.

## Review checklist

1. Open the pull request from `feat/bootstrap-upaoi-v0.2.0` to `main`.
2. Confirm the added files contain no tokens, production secrets, or data that must not be committed.
3. Review security boundaries, current limitations and deterministic adapter contracts in `docs/security.md`.
4. Let the `Test UPAOI` GitHub Actions matrix run; check Python 3.10, 3.12, and 3.13 jobs.
5. Confirm local tests, read-only fixture demo, and relative CLI entrypoints reproduce.
6. Require an independent review before approving any future plugin write adapter or production deployment.

## Local development

```bash
git clone https://github.com/NeuralBlitz/UPAOI.git
cd UPAOI
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
upaoi demo --db ./sandbox.sqlite
```

Do not store credentials or GitHub/Notion tokens in repository files. `UPAOI_GITHUB_TOKEN` and `UPAOI_NOTION_TOKEN` are separate runtime credentials and are **not** inherited from ChatGPT plugins.
