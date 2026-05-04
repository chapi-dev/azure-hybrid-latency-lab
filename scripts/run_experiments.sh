#!/usr/bin/env bash
# Run multiple experiments and print machine-readable summary lines.
# Usage:
#   ./run_experiments.sh [ITEMS] [RUNS_PER_WORKLOAD]
set -euo pipefail

ITEMS="${1:-500}"
RUNS="${2:-3}"

cd /home/azureuser/latency-lab
source .venv/bin/activate
set -a; . ./.env; set +a

# fetch latest scripts (they are checked out alongside .env)
ls chatty.py chunky.py >/dev/null

OUT="results-$(date +%Y%m%d%H%M%S).csv"
echo "workload,run_id,items,roundtrips,duration_ms" > "${OUT}"

for w in chatty chunky; do
  for i in $(seq 1 "${RUNS}"); do
    echo ">> ${w} run ${i}/${RUNS}"
    line="$(python "${w}.py" --items "${ITEMS}" | tail -n1)"
    rid="$(echo "$line" | sed -E 's/.*RUN_ID=([^ ]+).*/\1/')"
    rt="$(echo "$line" | sed -E 's/.*ROUNDTRIPS=([0-9]+).*/\1/')"
    dur="$(echo "$line" | sed -E 's/.*DURATION_MS=([0-9]+).*/\1/')"
    echo "${w},${rid},${ITEMS},${rt},${dur}" >> "${OUT}"
  done
done

echo "----- SUMMARY (${OUT}) -----"
cat "${OUT}"
