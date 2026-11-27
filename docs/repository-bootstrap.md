# GitHub repository integration and contribution workflow

**Canonical repository:** [NeuralBlitz/UPAOI](https://github.com/NeuralBlitz/UPAOI), created on 2026-11-22 and confirmed **public** on 2026-11-27.

The initial v0.2.0 implementation was added through [PR #1](https://github.com/NeuralBlitz/UPAOI/pull/1) and merged into `main`; GitHub Actions passed its Python 3.10/3.12/3.13 test matrix. This page supersedes the historical v0.2 bootstrap instructions that assumed the repository did not exist.

## Contribution process

1. Create a branch from a verified `main` commit.
2. Change only task-relevant files and document observable behavior, test coverage and limitations.
3. Run `python -m pip install -e .` then `python -m unittest discover -s tests -v` and local CLI smoke tests.
4. Open a reviewable pull request targeting `main`; do not force-push or rewrite history.
5. Confirm the GitHub Actions jobs, review the full file diff, then merge only after authorization and approval.
6. Record the new commit, PR, CI and implementation checkpoint in the canonical Notion blueprint.

`main` and public repository visibility are not evidence that the project is production-deployed. Do not commit any API keys, user datasets or local SQLite execution state to this public source repository.
