"""Latency probe — measure per-query round-trip time against PG.

Opens a single connection (so connect overhead is not counted), sends N small
`SELECT 1;` queries serially and records the per-query elapsed time. Writes a
CSV with columns: env_label, sample_idx, rtt_ms.

This is a deliberately minimal probe: a `SELECT 1;` is server-side O(microseconds),
so the wall-clock is dominated by the network round-trip + the protocol parsing,
which is exactly what we want to compare across environments.
"""
from __future__ import annotations
import argparse
import csv
import os
import statistics
import sys
import time

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--env-label", default=os.environ.get("ENV_LABEL", "unknown"))
    parser.add_argument("--out", default="latency_probe.csv")
    args = parser.parse_args()

    conninfo = os.environ["PG_CONNINFO"]
    print(f"latency_probe env={args.env_label} samples={args.samples}", flush=True)

    samples_ms: list[float] = []
    with psycopg.connect(conninfo, application_name=f"latency-probe-{args.env_label}") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Warmup query so the first sample isn't artificially slow due to TLS cache.
            cur.execute("SELECT 1;")
            for i in range(args.samples):
                t0 = time.perf_counter()
                cur.execute("SELECT 1;")
                cur.fetchone()
                rtt_ms = (time.perf_counter() - t0) * 1000.0
                samples_ms.append(rtt_ms)

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["env_label", "sample_idx", "rtt_ms"])
        for i, rtt in enumerate(samples_ms):
            w.writerow([args.env_label, i, f"{rtt:.3f}"])

    p50 = statistics.median(samples_ms)
    p95 = statistics.quantiles(samples_ms, n=20)[18]  # 95th percentile
    print(
        f"DONE env={args.env_label} samples={len(samples_ms)} "
        f"min={min(samples_ms):.2f}ms p50={p50:.2f}ms p95={p95:.2f}ms max={max(samples_ms):.2f}ms",
        flush=True,
    )


if __name__ == "__main__":
    main()
