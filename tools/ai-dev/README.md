# AI reviewer

This local tool reviews repository evidence and suggests one small improvement. It never
changes project files, creates patches, commits, or deploys anything.

## Run it

From the repository root:

```bash
./ai-dev
```

Choose Frontend, Virtual Garden, Plant Almanac, Plant Health, or the whole architecture.

## Stages

1. **PLAN** — select the target and collect relevant files.
2. **ACT** — Qwen 4B proposes one evidence-based improvement.
3. **OBSERVE** — Llama 3.1 checks the proposal against the same files.
4. **ADAPT** — a person accepts or rejects it and may add a note.

Ollama must be running locally. The proposer is `qwen3:4b-instruct`; the independent reviewer
is `llama3.1:8b`.

## Evidence

Every accepted or rejected recommendation creates:

```text
tools/ai-dev/logs/amy_z.md                         tracked clickable index
tools/ai-dev/logs/reports/amy_z/0001-virtual-garden.md
```

The index records the ID, scope, author, affected files, one-sentence change, status, optional
note, and a relative link to the full report. Placeholder features are not logged. The two
prompt files remain versioned under `tools/ai-dev/prompts/`.

Author is read from the signed-in GitHub CLI account, with `git config user.name` as an offline
fallback. Review logs before committing them because they become coursework evidence.
