# `results/notebook/` — analytical companion to the lab

This folder is the *checked-in, offline-readable analysis* of the lab's runs.
It is regenerated from the raw CSVs under `../raw/` and contains:

| File | What it is |
| --- | --- |
| `analysis.ipynb` | Jupyter notebook — open it on GitHub or in JupyterLab. Outputs are baked in, so you can read it without re-running. |
| `experiments.csv` | Merged `run_experiments.sh` output for **both** envs (chatty + chunky × 3 runs × 2 envs). |
| `latency_probe.csv` | 50 single-statement (`SELECT 1;`) RTT samples per env, produced by `scripts/latency_probe.py`. |
| `fig_*.png` | Standalone PNGs of every chart in the notebook (also embedded in the README). |

## How it was generated

```bash
# from the repo root, with both VMs already deployed
python scripts/merge_raw_csvs.py            # raw/*.csv  -> experiments.csv + latency_probe.csv
python scripts/build_notebook.py            # writes analysis.ipynb
python -m jupyter nbconvert --to notebook \
   --execute --inplace results/notebook/analysis.ipynb
```

## Two environments compared

| Env | Where it runs | Network to PG | Per-query RTT (p50) |
| --- | --- | --- | ---: |
| `onprem-wan` | Arc-onboarded VM in the on-prem VNet, reaching PG via vWAN, with `tc netem 80 ms ± 5 ms` injected on egress | simulated WAN | **79.31 ms** |
| `spoke-lan`  | VM inside the same VNet as PG | LAN | **0.48 ms** |

Same dataset (5000 items pre-seeded), same workload code (`scripts/chatty.py`,
`scripts/chunky.py`), same DB instance (`hyblat-pg-…postgres.database.azure.com`).
Only the network path changes.

## Headline result

| Workload | Round-trips | LAN duration | WAN duration | WAN slowdown |
| --- | ---: | ---: | ---: | ---: |
| `chatty` (N+1) | 1003 | 2.63 s | 85.46 s | **32.5×** |
| `chunky` (set-based) | 4 | 0.07 s | 1.16 s | 16.7× |

The WAN extra time matches `roundtrips × 80 ms` to within a few percent — the
WAN tax is exactly what you'd predict from first principles.

See `analysis.ipynb` for the full breakdown, including the boxplot of the
per-query RTT distribution and the log-log scatter showing both workloads
sliding along a line whose slope **is** the per-query RTT.
