#!/usr/bin/env bash
# Oracle equivalent of run_experiments.sh.
# Runs RUNS x chatty + RUNS x chunky and writes a machine-readable CSV.
# Usage:
#   ./run_experiments_oracle.sh [ITEMS] [RUNS]
set -euo pipefail

ITEMS="${1:-500}"
RUNS="${2:-3}"

cd "$(dirname "$0")"
# .env should export ORA_USER, ORA_PASSWORD, ORA_DSN, APPLICATIONINSIGHTS_CONNECTION_STRING
set -a; . ./.env; set +a

OUT="results-oracle-$(date +%Y%m%d%H%M%S).csv"
echo "workload,run_id,items,roundtrips,duration_ms" > "${OUT}"

for w in chatty chunky; do
  for i in $(seq 1 "${RUNS}"); do
    echo ">> ${w} run ${i}/${RUNS}"
    line="$(python "${w}_oracle.py" --items "${ITEMS}" | tail -n1)"
    rid="$(echo "$line" | sed -E 's/.*RUN_ID=([^ ]+).*/\1/')"
    rt="$(echo "$line"  | sed -E 's/.*ROUNDTRIPS=([0-9]+).*/\1/')"
    dur="$(echo "$line" | sed -E 's/.*DURATION_MS=([0-9]+).*/\1/')"
    echo "${w},${rid},${ITEMS},${rt},${dur}" >> "${OUT}"
  done
done

echo "----- SUMMARY (${OUT}) -----"
cat "${OUT}"
