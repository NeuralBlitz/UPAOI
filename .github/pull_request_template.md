## Scope

Describe the requested change and the governing blueprint requirement.

## Verification

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] CI matrix succeeds on Python 3.10, 3.12, and 3.13
- [ ] Change is covered by regression tests or a documented validation plan
- [ ] No credentials or sensitive data were committed
- [ ] Any provider write operations include authorization, read-back verification and failure reconciliation

## Risk and review

- Risk class: P0 / P1 / P2 / P3
- User approvals or deployment changes required:
- Recovery/rollback plan:
- Known limitations:
