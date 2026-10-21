# Testing evidence refresh — Amy — 22 October 2026 (Sydney)

Branch `amy/testing-fix`, based on main `228fec3`. This evidence was generated
from that base with the local Testing Review attribution fix and regression test
applied. The base commit identifies the source checkpoint; it does not claim the
fix is already in main or that these local results establish push CI.

## Correction

Testing Review previously assigned a multi-service scan only to its first
service. It now applies the combined result to every service explicitly covered
by the scan's file scope, and labels combined summaries. A failing combined
scan still fails; unrelated services gain no evidence. Regression coverage
checks successful and failed grouped scans replacing older individual results.

## Fresh verification

- 57 shared review-tool tests passed, including the grouped-scan regression.
- Ruff normal/security checks on changed Python files passed.
- All eight service test suites passed. JUnit includes 527 cases (Almanac's
  100 tests plus four subtests are represented as 104 JUnit cases).
- Full tracked-file Ruff security and detect-secrets checks passed for all eight
  services. Dependency audits passed for all eight; all four feature hook-style
  test commands passed. See `pre-commit-all-services.md`.
- Testing Review uses fresh local test/security evidence and reads the latest
  finished GitHub workflow runs. Its JSON lists the actual CI SHAs; those runs
  do not test this fix; branch CI must be verified separately after pushing.

These full scans use `trigger=report`. They are not proof of a new real commit's
hooks. Earlier actual commit evidence remains in the original report's history:
https://github.com/Bageutter/Plant-Management-System/blob/228fec3628cc49d006c7bea7186bd0b953599303/docs/evidence/release2/pre-commit-all-services.md
and in the individual contribution/report records. No hook was bypassed and no
secret baseline was regenerated. Raw security reports stay local/ignored.

## Remaining decisions

Read `testing-review.md` and its validation log. Review recommendations are not
Amy's approval: the human decision is left pending. Remaining endpoint-coverage
warnings are retained as quality improvements; they do not mean each student
failed the assignment's two-endpoint requirement. Cloud deployment work is out
of scope for this branch.

## Review outcome

Local Ollama completed ACT and independent OBSERVE in one iteration (no fallback).
Result: **ready_with_fixes**; 48 checks pass, six endpoint-coverage warnings,
zero failed/missing checks. Human decision remains **pending** under `amy`.

Execution occurred at `/private/tmp/pms-testing-fix`; the worktree was then moved
to `/Users/amyzhou/Documents/Plant-Management-System-testing-fix` for retention.
Historical command/log paths preserve where tests actually ran. The JSON's
transcript pointer is normalised to a repository-relative path after the move.
