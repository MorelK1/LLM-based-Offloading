#!/usr/bin/env bash
# Pipeline campaign: 5 models x 3 prompt strategies, 450 fixed samples each
# (sample_subset_450.json). Models run in PARALLEL (confirmed empirically:
# OpenRouter's new-account rate limit is scoped per model, e.g.
# "new-account-rpm/openai/gpt-5.4-mini-..." -- two different models run
# concurrently at --delay 0 produced zero interference, 24/24 ok). Within one
# model, the 3 strategies still run sequentially with --delay 5 against that
# model's own budget (20 req/min observed for at least one model; 2 calls/
# sample means --delay 5 keeps real pacing safely under that).
#
# Each (model, strategy) combo's console output goes to its own log in
# logs/, so this doesn't have to be watched live.
#
# Usage: nohup bash run_campaign_pipeline.sh > logs/campaign.log 2>&1 &

set -u
cd "$(dirname "$0")/../.."  # project root

MODELS=(
  "mistralai/mistral-small-3.2-24b-instruct"
  "deepseek/deepseek-v3.2"
  "meta-llama/llama-4-scout"
  "google/gemini-2.5-pro"
  "openai/gpt-5"
)
STRATEGIES=("zero_shot" "one_shot" "few_shot")
SAMPLE_IDS_FILE="expérimentations/public_safety/sample_subset_450.json"
LOG_DIR="expérimentations/public_safety/logs"
mkdir -p "$LOG_DIR"

run_model_sequence() {
  local model="$1"
  local model_tag
  model_tag="$(echo "$model" | tr '/' '-')"
  for strategy in "${STRATEGIES[@]}"; do
    local tag="${model_tag}__${strategy}"
    echo "=== $(date -u +%FT%TZ) starting $tag ===" >> "$LOG_DIR/${model_tag}.log"
    PYTHONPATH=src venv/bin/python3 expérimentations/public_safety/run_batch_full_graph.py \
      450 --delay 5 --model "$model" --prompt-strategy "$strategy" \
      --sample-ids-file "$SAMPLE_IDS_FILE" \
      >> "$LOG_DIR/${model_tag}.log" 2>&1 || true
    echo "=== $(date -u +%FT%TZ) finished $tag ===" >> "$LOG_DIR/${model_tag}.log"
  done
  echo "=== $(date -u +%FT%TZ) ALL STRATEGIES DONE for $model ===" >> "$LOG_DIR/${model_tag}.log"
}

for model in "${MODELS[@]}"; do
  run_model_sequence "$model" &
done

wait
echo "=== campaign done ==="
