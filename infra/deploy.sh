#!/usr/bin/env bash
# Deploy the Hybrid Latency Lab.
# Requires: az CLI logged in, current sub set to your target.
set -euo pipefail

LOCATION="${LOCATION:-westeurope}"
RG="${RG:-rg-hybrid-latency-lab}"
PREFIX="${PREFIX:-hyblat}"
SSH_KEY_FILE="${SSH_KEY_FILE:-$HOME/.ssh/hyblat_id_ed25519.pub}"

if [ ! -f "$SSH_KEY_FILE" ]; then
  echo "Missing SSH public key at $SSH_KEY_FILE. Generate with:"
  echo "  ssh-keygen -t ed25519 -f \"${SSH_KEY_FILE%.pub}\" -N '' -C hybrid-latency-lab"
  exit 1
fi

PG_PASSWORD="${PG_PASSWORD:-$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)Aa1!}"
echo "Generated PG password (save it): $PG_PASSWORD"

az group create -n "$RG" -l "$LOCATION" -o none

az deployment group create \
  -g "$RG" \
  -n "lab-$(date +%Y%m%d%H%M%S)" \
  -f main.bicep \
  -p location="$LOCATION" prefix="$PREFIX" \
     sshPublicKey="$(cat "$SSH_KEY_FILE")" \
     pgAdminPassword="$PG_PASSWORD" \
  -o table

echo "Deployment complete."
