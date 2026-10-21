# Almanac comparison review and human-review interface

Evidence date: 21 October 2026 (Australia/Sydney).
Branch: `amy/almanac-multi-agent`.
Implementation commits: `73c4779` (shared Reviewer) and `435ea0c` (Almanac chat).
These commits are local; no push or GitHub Actions result is established here.

## Observed defect

The existing chat question was **Compare basil and zucchini**. The draft claimed
both plants require full sun and soil pH 6.0–7.0. The retrieved Basil - Genovese
record contains those values; the retrieved Zucchini record does not. The old
review reported both citations as unused because the answer was organised by
field rather than exact plant-title paragraphs. That branch skipped the factual
review, leaving the actual unsupported claims unexplained.

## Shared server correction

`ai-services/multi-agent-server/reviewer.py` now reviews field-led comparisons
against the cited records together, preserving plant identities. Absence of an
exact title label alone is no longer proof of an unused citation. Positive
“both/each” sunlight, water and pH claims need a corresponding recorded field
for every cited plant. Chunks for the same plant are combined for that check.
The existing source-by-source review remains for explicitly labelled answers.

A narrow consistency check discards model objections that treat an explicit
“not recorded” statement as false solely because the source does not record
that field. Actual contradictions and unsupported positive claims remain
review findings. Unknown citations and quoted-issue validation remain active.

## Almanac interface correction

- Readable workflow status and concern summary replace exposed review JSON.
- Old “unused citation” findings are explained as attribution-check concerns
  with plant names; historical workflow findings are preserved.
- Cited references show exact recorded facts, explicit “Not recorded” values,
  source links and expandable complete passages.
- Request changes is selected when review concerns or evidence gaps exist.
  Decision-specific help and an optional feedback helper explain the next step.
- Raw workflow, model output and citation identifiers remain in collapsed
  Technical details. Text is escaped and source links require HTTP(S).
- Existing owner checks, CSRF and server-side review-state checks are retained.

## Verification

- `almanac/.venv/bin/python -m pytest -q almanac/tests`: **89 passed**.
- From `ai-services/multi-agent-server`,
  `../../almanac/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`:
  **24 passed**.
- Ruff on changed Python files, `git diff --check`, and
  `docker compose config --quiet`: passed.
- A real local Ollama review replayed the **same saved draft and source evidence**.
  It returned `revise` with two grounded findings: Zucchini has no recorded
  sunlight or soil pH. No unused-citation finding remained. See
  `comparison-before-after.json` for the preserved input, before and after.
- Browser inspection of the running Almanac chat confirmed readable concerns,
  exact/missing source facts, collapsed diagnostics and Request changes selected.
  No decision was submitted on the user's existing comparison.

## Evidence files

- `comparison-before-after.json`: public plant references and model outputs;
  account cookies, user IDs and authentication data are excluded.
- `almanac-tests.txt`, `shared-server-tests.txt`: automated test results.
- `readable-review.png`, `saved-facts.png`, `review-controls.png`: running UI.
- `pr-description.md`: reviewable change/validation summary.

These are local validation results, not a merged release, post-push CI result,
cloud deployment, or general accuracy estimate. Existing stored reviews are not
rewritten; new runs use the corrected reviewer. Record a commit SHA and CI run
here after pushing and checking GitHub Actions. This workflow review is
separate from the assignment's three report-review modes.

## Integration with main

The branch incorporates `main` at `f6cc21a`, including the Azure deployment,
report-review validator and Plant Health Multi-Agent integration. Conflict
resolution keeps the updated workflow documentation and security-runner options.
The shared Reviewer retains both field-led plant comparisons and upstream
handling of quotes that do not match the answer. Unlabelled narrative answers
still receive per-record review; field-led comparisons and shared claims use the
joint evidence check. A regression test checks that a mangled model quote cannot
erase deterministic comparison findings or fail the whole review.

Validation of the combined tree: **42 shared-server tests** and **31 report-review
validator tests** passed, along with Ruff on the resolved Python files and
`docker compose config --quiet`. The earlier logs and screenshots above remain
the original feature-run evidence; they do not claim post-push CI success.
