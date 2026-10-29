#!/usr/bin/env bash
# Create the `-demo` model variants that docker-compose.demo.yml and wsl-demo-up.sh use:
# the same models with `num_thread 6`. Ollama's default of 16 threads runs about 80x
# slower on the hybrid-core recording laptop, so the demo stack names these instead.
# `ollama create` shares the base model's weights, so each variant costs a few KB.
#
#   bash scripts/demo/create-demo-models.sh                      # qwen3:4b-instruct, qwen2.5vl:3b
#   NUM_THREAD=8 bash scripts/demo/create-demo-models.sh qwen3:4b-instruct
#
# Runs wherever `ollama` is served (natively in WSL for the recording). OLLAMA_BIN points
# at the binary when it is not on PATH (the WSL laptop keeps it in ~/ollama/bin).
set -euo pipefail
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/ollama/bin/ollama")}"
NUM_THREAD="${NUM_THREAD:-6}"
models=("$@")
[[ ${#models[@]} -gt 0 ]] || models=(qwen3:4b-instruct qwen2.5vl:3b)

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
for base in "${models[@]}"; do
  "$OLLAMA_BIN" show "$base" >/dev/null 2>&1 || "$OLLAMA_BIN" pull "$base"
  {
    echo "FROM $base"
    echo "PARAMETER num_thread $NUM_THREAD"
  } > "$tmp"
  "$OLLAMA_BIN" create "${base}-demo" -f "$tmp"
  echo "created ${base}-demo (num_thread $NUM_THREAD)"
done
