#!/usr/bin/env bash
# Run on the on-prem VM. Sets it up to look "non-Azure-like" and prepares
# the experiment environment.
#
# Usage:
#   sudo ./setup_onprem.sh <PG_FQDN> <PG_PASSWORD> <APPINSIGHTS_CONN_STRING> [LATENCY_MS]
#
# - Sets a corp-style hostname / DNS suffix
# - Installs python deps
# - Optionally injects egress latency with `tc netem` to simulate WAN distance
set -euo pipefail

PG_FQDN="${1:?missing PG_FQDN}"
PG_PASSWORD="${2:?missing PG_PASSWORD}"
APPI_CS="${3:?missing APPLICATIONINSIGHTS_CONNECTION_STRING}"
LATENCY_MS="${4:-80}"

NEW_HOSTNAME="db-batch-server"
NEW_FQDN="${NEW_HOSTNAME}.corp.local"

echo "[1/6] Installing OS deps…"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3-venv python3-pip iproute2 dnsutils postgresql-client \
    iperf3 mtr-tiny jq curl

echo "[2/6] Setting hostname/DNS suffix to ${NEW_FQDN}…"
hostnamectl set-hostname "${NEW_HOSTNAME}"
if ! grep -q "${NEW_FQDN}" /etc/hosts; then
  sed -i "/127\.0\.1\.1/d" /etc/hosts
  echo "127.0.1.1 ${NEW_FQDN} ${NEW_HOSTNAME}" >> /etc/hosts
fi

echo "[3/6] Pinning a 'corp' alias for the database…"
PG_IP="$(getent hosts "${PG_FQDN}" | awk '{print $1}' | head -n1 || true)"
if [ -z "${PG_IP}" ]; then
  echo "WARN: could not resolve ${PG_FQDN} yet (DNS may need a moment)"
else
  if ! grep -q "pg-prod.corp.local" /etc/hosts; then
    echo "${PG_IP} pg-prod.corp.local" >> /etc/hosts
  fi
fi

echo "[4/6] Setting up python venv + deps…"
sudo -u azureuser bash <<EOF
set -e
cd /home/azureuser
mkdir -p latency-lab && cd latency-lab
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet psycopg[binary] azure-monitor-opentelemetry opentelemetry-instrumentation-psycopg python-dotenv
EOF

echo "[5/6] Writing /home/azureuser/latency-lab/.env (NOT committed)…"
cat > /home/azureuser/latency-lab/.env <<EOF
PG_CONNINFO="host=pg-prod.corp.local dbname=latencylab user=pgadmin password=${PG_PASSWORD} sslmode=require"
APPLICATIONINSIGHTS_CONNECTION_STRING="${APPI_CS}"
AZURE_LOG_LEVEL=warning
OTEL_LOG_LEVEL=warn
EOF
chown azureuser:azureuser /home/azureuser/latency-lab/.env
chmod 600 /home/azureuser/latency-lab/.env

echo "[6/6] Adding ${LATENCY_MS}ms egress latency via tc netem (simulating WAN)…"
DEV="$(ip -o -4 route show default | awk '{print $5}' | head -n1)"
tc qdisc del dev "${DEV}" root 2>/dev/null || true
tc qdisc add dev "${DEV}" root netem delay "${LATENCY_MS}ms" 5ms distribution normal

echo "DONE. Hostname=$(hostname -f). Egress on ${DEV} delayed by ${LATENCY_MS}ms (+/-5ms)."
echo "Test: ping -c 4 pg-prod.corp.local"
