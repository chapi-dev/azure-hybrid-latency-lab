#!/usr/bin/env bash
# Post-deploy: copy scripts, setup on-prem VM, seed DB, run experiments,
# pull results, plot. Idempotent. Re-run safely.
set -euo pipefail

RG="${RG:-rg-hybrid-latency-lab}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/hyblat_id_ed25519}"
ITEMS="${ITEMS:-500}"
RUNS="${RUNS:-3}"
LATENCY_MS="${LATENCY_MS:-80}"
PG_PASSWORD="${PG_PASSWORD:?Set PG_PASSWORD env var to the password from deploy.sh}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/7] Reading deployment outputs…"
DN="$(az deployment group list -g "$RG" --query '[0].name' -o tsv)"
PG_FQDN="$(az deployment group show -g "$RG" -n "$DN" --query properties.outputs.pgFqdn.value -o tsv)"
APPI_CS="$(az deployment group show -g "$RG" -n "$DN" --query properties.outputs.appInsightsConnectionString.value -o tsv)"
ONPREM_IP="$(az deployment group show -g "$RG" -n "$DN" --query properties.outputs.vmOnpremPublicIp.value -o tsv)"
SPOKE_IP="$(az deployment group show -g "$RG" -n "$DN" --query properties.outputs.vmSpokePublicIp.value -o tsv)"
echo "  PG=$PG_FQDN onprem=$ONPREM_IP spoke=$SPOKE_IP"

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SCP="scp -i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

echo "[2/7] Pushing scripts to on-prem VM…"
$SSH "azureuser@$ONPREM_IP" "mkdir -p /home/azureuser/latency-lab"
$SCP "$ROOT/scripts/chatty.py" "$ROOT/scripts/chunky.py" "$ROOT/scripts/seed.py" \
     "$ROOT/scripts/run_experiments.sh" \
     "azureuser@$ONPREM_IP:/home/azureuser/latency-lab/"

echo "[3/7] Pushing setup script and running it (sudo)…"
$SCP "$ROOT/scripts/setup_onprem.sh" "azureuser@$ONPREM_IP:/tmp/"
$SSH "azureuser@$ONPREM_IP" "sudo bash /tmp/setup_onprem.sh '$PG_FQDN' '$PG_PASSWORD' '$APPI_CS' $LATENCY_MS"

echo "[4/7] Pushing scripts to spoke VM and seeding DB (no latency injection)…"
$SSH "azureuser@$SPOKE_IP" "mkdir -p /home/azureuser/latency-lab"
$SCP "$ROOT/scripts/seed.py" "azureuser@$SPOKE_IP:/home/azureuser/latency-lab/"
$SSH "azureuser@$SPOKE_IP" "sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip postgresql-client && python3 -m venv ~/latency-lab/.venv && source ~/latency-lab/.venv/bin/activate && pip install --quiet psycopg[binary]"
$SSH "azureuser@$SPOKE_IP" "source ~/latency-lab/.venv/bin/activate && PG_CONNINFO='host=$PG_FQDN dbname=latencylab user=pgadmin password=$PG_PASSWORD sslmode=require' python ~/latency-lab/seed.py --rows 5000"

echo "[5/7] Running experiments on on-prem VM…"
$SSH "azureuser@$ONPREM_IP" "cd /home/azureuser/latency-lab && bash run_experiments.sh $ITEMS $RUNS"

echo "[6/7] Pulling results CSV…"
mkdir -p "$ROOT/results"
$SCP "azureuser@$ONPREM_IP:/home/azureuser/latency-lab/results-*.csv" "$ROOT/results/"

echo "[7/7] Generating charts…"
LATEST="$(ls -t "$ROOT"/results/results-*.csv | head -n1)"
python3 "$ROOT/scripts/plot_results.py" --csv "$LATEST" --out "$ROOT/results/"

echo
echo "DONE. Charts in $ROOT/results/"
