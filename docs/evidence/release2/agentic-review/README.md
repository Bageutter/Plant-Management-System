# Agentic-loop review logs (Release 2, criterion 8)

The shared, non-containerised agentic loop (`tools/ai-loop/evidence_review.py`, Plan → Act →
Observe → Adapt on local Ollama) reviewing the Release 2 evidence. Each run writes the
loop's own sinks under `tools/ai-loop/logs/` (`<mode>.jsonl` and
`reports/<mode>/<run_id>.md`) and copies its review/validation log here as
`<mode>-<run stamp>-review.md` / `.json`; `<mode>-latest-review.*` is the newest run of
each mode. The Cloud Deployment Report Review copies its log next to the deployment
report instead (`../cloud-deployment/`). Commands and the full check list:
[`tools/ai-loop/README.md`](../../../../tools/ai-loop/README.md).

All runs below: 21 October 2026, CPU-only laptop, proposer `gemma3:4b`, reviewer
`qwen2.5vl:3b` (`--model gemma3:4b --review-model qwen2.5vl:3b`), two iterations.

| Log | Mode | Evidence reviewed | Verdict | Loop |
| --- | --- | --- | --- | --- |
| [`multi-agent-20261021-112032-3a7541-review.md`](multi-agent-20261021-112032-3a7541-review.md) | `multi-agent` | Virtual Garden export in `docs/evidence/release2/` (6 workflows, 11 runs) | **pass** — every code check held | capped at 2: the model invented six "no human feedback" findings that the grounding contradicts; the code removed them and the deterministic OBSERVE sent the draft back twice |
| [`multi-agent-20261021-112114-0fe60f-review.md`](multi-agent-20261021-112114-0fe60f-review.md) | `multi-agent` | Plant Health export `docs/evidence/release2/local-deployment/` (2 workflows, 3 runs; the folder lands with PR #82) | **pass** | capped at 2: three invented findings removed, decision corrected from `pass_with_findings` |
| [`multi-agent-20261021-112137-a3341b-review.md`](multi-agent-20261021-112137-a3341b-review.md) | `multi-agent` | The live Multi-Agent Server at `http://127.0.0.1:8003` (`--server`; same two health workflows, fetched through `/workflow/audit/*` and `/workflow/metrics`) | **pass** | capped at 2: one invented citation finding removed |
| [`testing-20261021-112152-40927a-review.md`](testing-20261021-112152-40927a-review.md) | `testing` | `pre-commit/health-guhan.md` and `post-commit/health-guhan/` (both land with PR #82) | **pass** — four scans PASS, push run, two endpoint tests and 60 regressions green | capped at 2: two "check passed" observations the model listed as findings were removed |

Reading the logs: the *Findings* table is the review's result (only checks computed in
code can be findings); *Code corrections applied to the final draft* lists every change
the code made to the model's output, and the *Summary* says how many of the model's
findings were removed, so its prose is read with that in mind. Each log ends with the
*Human confirmation* checklist: the review is advisory and the team confirms it.

Regenerate after new evidence lands:

```bash
python tools/ai-loop/evidence_review.py --mode multi-agent --model gemma3:4b --review-model qwen2.5vl:3b
python tools/ai-loop/evidence_review.py --mode multi-agent --evidence-dir docs/evidence/release2/local-deployment --model gemma3:4b --review-model qwen2.5vl:3b
python tools/ai-loop/evidence_review.py --mode testing --model gemma3:4b --review-model qwen2.5vl:3b
```
