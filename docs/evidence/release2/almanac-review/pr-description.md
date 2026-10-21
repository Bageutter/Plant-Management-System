## Changes

- Connect the existing authenticated Almanac chat to the shared Multi-Agent Server, saving the workflow and evidence with its chat owner and retaining status recovery, CSRF and owner checks.
- Replace exposed workflow/reviewer JSON with readable status, concerns, plant names and a proposed answer.
- Show cited records as saved-fact cards, mark missing values explicitly, and offer source links and full passages for checking the draft.
- Default to Request changes when the reviewer flags concerns or evidence is missing; explain each decision and offer editable suggested feedback. Keep raw diagnostics under Technical details.
- Fix the shared Reviewer’s comparison path: an answer organised by field no longer produces unused-citation findings merely because exact source-title labels are absent, and the cited evidence still receives factual review.
- Require support in every cited plant record for shared sunlight, water and pH claims; combine chunks for the same plant so missing fields in one chunk do not create false warnings.
- Suppress contradictory model objections that treat a supported “not recorded” statement as an unsupported positive claim, while preserving source contradictions and other positive-claim findings.
- Add regression tests and sanitised before/after evidence under docs/evidence/release2/almanac-review/.

## Validation

- Almanac suite: 89 passed.
- Shared Multi-Agent suite: 24 passed.
- Changed Python files pass Ruff; Compose configuration and git diff checks pass.
- Real local Ollama replay of the saved Basil/Zucchini comparison reports the two unsupported Zucchini sunlight/pH claims, replacing the old unused-citation messages.
- Browser checked the readable source facts, default correction decision and collapsed diagnostics. Existing user review decisions were not changed.

The shared Reviewer correction (`73c4779`) and Almanac integration (`435ea0c`) are separate local commits. These results do not establish cloud deployment or new post-push CI success.
