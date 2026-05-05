# Azure Hybrid Latency Lab

> A reproducible lab that **proves** the cost of "chatty" round-trips against a remote DB over a hybrid network — using **real Azure Virtual WAN**, an **Azure Arc–onboarded** "on-prem" Linux VM, a real **PostgreSQL Flexible Server**, and **Application Insights** to measure every single round-trip.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[🇪🇸 Versión en español](README.md) · [📖 Step-by-step guide (Spanish)](GUIA.md)

## Why this exists

A common pattern in hybrid architectures: a heavy batch process running on-prem talks to a database in Azure across a long distance. The DB is fast, the link is wide, but the batch takes hours because it issues thousands of tiny queries. Each query pays a full WAN RTT.

This lab reproduces that scenario end-to-end on Azure and measures it. You get:

- A real Azure **Virtual WAN** with a Standard hub.
- A **spoke VNet** with an Azure VM and an Azure Database for **PostgreSQL Flexible Server** (VNet-injected, private DNS).
- An **"on-prem" VNet** with a Linux VM that:
  - has a `corp.local` hostname (not `.cloudapp.azure.com`),
  - reaches the DB by a custom DNS alias,
  - is **Arc-onboarded** so it shows up in Azure as a Hybrid Compute server,
  - has **`tc netem`** injecting realistic WAN latency on its egress.
- Two Python workloads doing the **same logical work** against the DB:
  - `chatty.py` — N+1 round-trips
  - `chunky.py` — set-based / `COPY` (constant round-trips)
- **Application Insights** + **Log Analytics** + **Network Watcher Connection Monitor** for end-to-end correlation.
- Generated PNG charts under `results/` using the actual telemetry from a real run.

## Architecture

```mermaid
flowchart LR
    subgraph onprem["VNet 'on-prem' (10.100.0.0/16)"]
        OP["vm-onprem<br/>Ubuntu 24.04<br/>db-batch-server.corp.local<br/>+ Arc Connected Machine<br/>+ tc netem 80ms"]
    end

    subgraph hub["Azure vWAN Hub (10.0.0.0/24)"]
        H[(Virtual Hub<br/>Standard)]
    end

    subgraph spoke["VNet 'spoke' (10.10.0.0/16)"]
        VS["vm-spoke<br/>Ubuntu 24.04"]
        PG[("PostgreSQL Flex<br/>B1ms · VNet-injected<br/>private.postgres.database.azure.com")]
    end

    subgraph mon["Observability"]
        LAW[(Log Analytics)]
        AI[(Application Insights)]
        NW[(Network Watcher<br/>Connection Monitor)]
    end

    OP -- "vWAN spoke conn" --> H
    H -- "vWAN spoke conn" --> VS
    H --> PG
    OP -. telemetry .-> AI
    VS -. telemetry .-> AI
    AI --> LAW
    NW --> LAW
```

## Repo layout

```
.
├── infra/             Bicep modules + deploy.sh / deploy.ps1
│   ├── main.bicep
│   └── modules/
│       ├── observability.bicep
│       ├── vwan.bicep
│       ├── spoke-network.bicep
│       ├── onprem-network.bicep
│       ├── vm.bicep
│       └── postgres.bicep
├── scripts/
│   ├── seed.py             # creates schema + N rows in PG
│   ├── chatty.py           # N+1 anti-pattern, Application Insights instrumented
│   ├── chunky.py           # bulk / set-based, same logical work
│   ├── plot_results.py     # generates charts from the run CSV
│   ├── setup_onprem.sh     # one-shot setup on the on-prem VM (DNS, deps, netem)
│   ├── run_experiments.sh  # runs N×chatty + N×chunky and writes CSV
│   └── requirements.txt
├── monitoring/
│   ├── queries.kql         # KQL for App Insights & LAW
│   └── workbook.json       # Azure Workbook
├── results/                # PNG charts + raw CSV from the actual run
├── docs/                   # supplemental docs / architecture
├── LICENSE                 # MIT
└── README.md
```

## Prerequisites

- An Azure subscription where you can create:
  - resource groups, VNets, vWAN, VMs, PostgreSQL Flexible Server, Log Analytics, Application Insights
- Local tools: **az CLI**, **bicep** (bundled), **ssh-keygen**, **bash** (or PowerShell), **python ≥ 3.10** (only needed locally if you want to regenerate charts)

## Deploy (45 min)

```bash
# 1. Generate an SSH keypair
ssh-keygen -t ed25519 -f ~/.ssh/hyblat_id_ed25519 -N '' -C hybrid-latency-lab

# 2. Login + select the right sub
az login
az account set --subscription "<your-subscription>"

# 3. Deploy
cd infra
./deploy.sh                # writes a generated PG password to stdout — save it
```

The deployment creates one resource group `rg-hybrid-latency-lab` containing:

| Resource | Purpose |
| --- | --- |
| `hyblat-vwan` + `hyblat-hub` | Virtual WAN Standard with one hub (~25 min to provision) |
| `hyblat-spoke-vnet` | Spoke VNet attached to hub |
| `hyblat-onprem-vnet` | "On-prem" VNet attached to hub |
| `hyblat-vm-spoke` | Standard_B2s_v2, Ubuntu 24.04 |
| `hyblat-vm-onprem` | Standard_B2s_v2, Ubuntu 24.04 |
| `hyblat-pg-…` | PostgreSQL Flexible Server B1ms, VNet-injected |
| `hyblat-law` / `hyblat-ai` | Log Analytics + Application Insights |

Ports `22/tcp` are open from the internet to both VMs (lab — restrict in production).

## Run the experiment

```bash
# pick up the deployment outputs
RG=rg-hybrid-latency-lab
PG_FQDN=$(az postgres flexible-server list -g $RG --query "[0].fullyQualifiedDomainName" -o tsv)
PG_PASSWORD="<the password printed by deploy.sh>"
APPI_CS=$(az monitor app-insights component show -g $RG -a hyblat-ai --query connectionString -o tsv)
ONPREM_IP=$(az vm show -d -g $RG -n hyblat-vm-onprem --query publicIps -o tsv)

# 1. Onboard the "on-prem" VM (DNS, deps, latency injection)
scp -i ~/.ssh/hyblat_id_ed25519 scripts/setup_onprem.sh azureuser@$ONPREM_IP:/tmp/
scp -i ~/.ssh/hyblat_id_ed25519 scripts/{chatty,chunky,seed}.py azureuser@$ONPREM_IP:/home/azureuser/latency-lab/
scp -i ~/.ssh/hyblat_id_ed25519 scripts/run_experiments.sh azureuser@$ONPREM_IP:/home/azureuser/latency-lab/
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP \
  "sudo bash /tmp/setup_onprem.sh '$PG_FQDN' '$PG_PASSWORD' '$APPI_CS' 80"

# 2. Onboard to Azure Arc (test-mode, since it's actually an Azure VM)
#    The installer reads MSFT_ARC_TEST from systemd's environment, NOT the shell,
#    so you must `systemctl set-environment` it first or the installer refuses.
ssh azureuser@$ONPREM_IP <<'EOF'
sudo systemctl set-environment MSFT_ARC_TEST=true
curl -fsSL -o /tmp/install_arc.sh https://aka.ms/azcmagent
sudo bash /tmp/install_arc.sh

# Pre-create a least-privilege SP with the Arc onboarding role:
#   az ad sp create-for-rbac -n hyblat-arc-onboard \
#     --role "Azure Connected Machine Onboarding" \
#     --scopes /subscriptions/<SUB>/resourceGroups/rg-hybrid-latency-lab
sudo azcmagent connect \
  --service-principal-id <APP_ID> --service-principal-secret <SECRET> \
  --tenant-id <TENANT_ID> --subscription-id <SUB_ID> \
  --resource-group rg-hybrid-latency-lab --location westeurope \
  --resource-name hyblat-onprem-arc --tags 'lab=hyblat'
EOF

# 3. Seed the DB (run from the spoke VM where the route is short)
SPOKE_IP=$(az vm show -d -g $RG -n hyblat-vm-spoke --query publicIps -o tsv)
ssh azureuser@$SPOKE_IP \
  "PG_CONNINFO='host=$PG_FQDN dbname=latencylab user=pgadmin password=$PG_PASSWORD sslmode=require' python3 seed.py --rows 5000"

# 4. Run the experiments from the on-prem VM
ssh azureuser@$ONPREM_IP "cd /home/azureuser/latency-lab && bash run_experiments.sh 500 3"
scp -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP:/home/azureuser/latency-lab/results-*.csv results/

# 5. Plot
python scripts/plot_results.py --csv results/results-*.csv --out results/
```

## What the charts show

Generated in `results/` after a real run:

| Chart | What it shows |
| --- | --- |
| `chart_roundtrips.png` | Mean round-trips per workload (chatty ≫ chunky). |
| `chart_duration.png` | Mean wall-clock duration. The gap is the WAN tax. |
| `chart_scatter.png` | log-log scatter of round-trips vs duration. The slope ≈ RTT. |
| `chart_per_run.png` | Run-by-run consistency check. |

## Real run results (3 × chatty + 3 × chunky, 500 items, 80 ms simulated WAN RTT)

The CSV in `results/` was produced by the actual deployed lab:

| Workload | avg round-trips | avg duration | x slower |
| --- | ---: | ---: | ---: |
| chunky | **4** | **1.18 s** | 1.0× (baseline) |
| chatty | **1003** | **85.67 s** | **72.7×** |

Same logical work, same DB, same network. The only difference is whether the
client batches its work or pays the WAN RTT on every row.

![Round-trips per workload](results/chart_roundtrips.png)
![Duration per workload](results/chart_duration.png)
![Round-trips vs duration (log-log)](results/chart_scatter.png)
![Per-run duration](results/chart_per_run.png)

## Arc + Connection Monitor (verified)

The "on-prem" VM is onboarded as an **Azure Arc Connected Machine**, so it shows
up in the portal under **Servers - Azure Arc** as a hybrid resource — exactly as
a real on-prem box would, even though it's a managed Azure VM under the hood
(this is what `MSFT_ARC_TEST=true` is for).

```bash
az connectedmachine show -g rg-hybrid-latency-lab -n hyblat-onprem-arc \
  --query "{name:name, status:status, osName:osName, agentVersion:agentVersion}" -o table
# Name                Status     OsName    AgentVersion
# hyblat-onprem-arc   Connected  linux     1.63.x
```

A **Network Watcher Connection Monitor** (`hyblat-cm-onprem-to-pg`) probes the
PostgreSQL Flexible Server's private IP on TCP/5432 every 60 s from the on-prem
VM, and writes the results to the same Log Analytics workspace as the
applicative telemetry — so you can correlate the WAN RTT trace with the
chatty/chunky run timeline:

```kusto
NWConnectionMonitorTestResult
| where TestGroupName == "DefaultTestGroup"
| summarize avg(AvgRoundTripTimeMs) by bin(TimeGenerated, 5m), TestResult
| render timechart
```

This is what closes the loop on the original ask: "I want to know the network RTT and
the application's round-trip count, side by side, on the same time axis."

## WAN vs LAN comparison (Jupyter notebook)

A second pass of the experiment was run from **both** ends:

- `onprem-wan`: from the Arc-onboarded "on-prem" VM, with `tc netem 80 ms` on egress.
- `spoke-lan`: from a VM inside the same VNet as PostgreSQL (~0.5 ms RTT).

Same scripts, same DB, same dataset. The full analysis — including a 50-sample
per-query latency probe and a "WAN tax = roundtrips × RTT" prediction check —
is checked into [`results/notebook/analysis.ipynb`](results/notebook/analysis.ipynb)
so you can read it offline (outputs are baked in) or re-execute it locally.

| Workload | Round-trips | LAN duration | WAN duration | WAN slowdown |
| --- | ---: | ---: | ---: | ---: |
| `chatty` (N+1)        | 1003 | 2.63 s | 85.46 s | **32.5×** |
| `chunky` (set-based)  |    4 | 0.07 s |  1.16 s |   16.7×   |

![Per-query RTT — onprem (WAN) vs spoke (LAN)](results/notebook/fig_01_per_query_rtt.png)
![The WAN tax = roundtrips × per-query RTT](results/notebook/fig_03_wan_tax_prediction.png)
![Round-trips vs duration: same slope, two altitudes](results/notebook/fig_05_scatter_log_log.png)

## Querying telemetry yourself

See `monitoring/queries.kql`. Highlights:

- Run summary by workload (`avg_dur_ms`, `avg_rt`, **`ms_per_roundtrip`**)
- Time-series of round-trips (chatty looks like a wall, chunky looks like 2 spikes)
- Total wall-clock vs sum of dependency durations (the gap is client/CPU time)
- Connection Monitor RTT during the experiment

Import `monitoring/workbook.json` into Azure Portal → Workbooks → **+ New** → **Advanced editor** to get a pre-baked dashboard.

## Cost

≈ **$0.40/hour** while deployed:

| Resource | Cost (approx., West Europe) |
| --- | --- |
| vWAN hub Standard | $0.25/h |
| 2× B2s VMs | $0.08/h |
| PG Flex B1ms | $0.02/h |
| LAW + App Insights ingestion | a few cents/day |

**Tear it all down** with:

```bash
az group delete -n rg-hybrid-latency-lab --yes --no-wait
```

## License

MIT — see [LICENSE](LICENSE).
