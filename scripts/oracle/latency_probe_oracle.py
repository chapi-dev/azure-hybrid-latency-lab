"""Latency probe (Oracle) — measure per-query round-trip time.

Mirror of latency_probe.py: 1 single connection, N small `SELECT 1 FROM dual;`
queries, write per-sample CSV with columns env_label, sample_idx, rtt_ms.
"""
from __future__ import annotations
import argparse
import csv
import os
import statistics
import time

import oracledb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--env-label", default=os.environ.get("ENV_LABEL", "unknown"))
    parser.add_argument("--out", default="latency_probe_oracle.csv")
    args = parser.parse_args()

    user = os.environ["ORA_USER"]
    password = os.environ["ORA_PASSWORD"]
    dsn = os.environ["ORA_DSN"]

    print(f"latency_probe_oracle env={args.env_label} samples={args.samples}", flush=True)

    samples_ms: list[float] = []
    with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM dual")  # warmup
            cur.fetchone()
            for _ in range(args.samples):
                t0 = time.perf_counter()
                cur.execute("SELECT 1 FROM dual")
                cur.fetchone()
                samples_ms.append((time.perf_counter() - t0) * 1000.0)

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["env_label", "sample_idx", "rtt_ms"])
        for i, rtt in enumerate(samples_ms):
            w.writerow([args.env_label, i, f"{rtt:.3f}"])

    p50 = statistics.median(samples_ms)
    p95 = statistics.quantiles(samples_ms, n=20)[18]
    print(
        f"DONE env={args.env_label} samples={len(samples_ms)} "
        f"min={min(samples_ms):.2f}ms p50={p50:.2f}ms p95={p95:.2f}ms max={max(samples_ms):.2f}ms",
        flush=True,
    )


if __name__ == "__main__":
    main()
