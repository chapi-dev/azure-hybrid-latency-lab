"""Merge raw per-env CSVs into combined CSVs for the analysis notebook."""
import csv
import glob
import os

raw = os.path.join(os.path.dirname(__file__), os.pardir, "results", "raw")
nb = os.path.join(os.path.dirname(__file__), os.pardir, "results", "notebook")
os.makedirs(nb, exist_ok=True)

with open(os.path.join(nb, "experiments.csv"), "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["env_label", "workload", "run_id", "items", "roundtrips", "duration_ms"])
    for f in sorted(glob.glob(os.path.join(raw, "experiments_*.csv"))):
        env = os.path.basename(f).replace("experiments_", "").replace(".csv", "")
        with open(f) as r:
            rd = csv.reader(r)
            next(rd)
            for row in rd:
                w.writerow([env, *row])

with open(os.path.join(nb, "latency_probe.csv"), "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["env_label", "sample_idx", "rtt_ms"])
    for f in sorted(glob.glob(os.path.join(raw, "latency_probe_*.csv"))):
        with open(f) as r:
            rd = csv.reader(r)
            next(rd)
            for row in rd:
                w.writerow(row)

print("OK merged")
