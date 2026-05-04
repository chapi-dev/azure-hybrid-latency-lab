"""Pull telemetry from PG run_log + App Insights, plot results.

Usage (from a workstation that has az CLI logged in):
  python plot_results.py \
    --rg rg-hybrid-latency-lab \
    --ai-name hyblat-ai \
    --csv results-YYYYMMDDHHMMSS.csv \
    --out ../results/

Generates:
  - chart_roundtrips.png    : bar chart of roundtrips per workload (avg)
  - chart_duration.png      : bar chart of total duration ms per workload
  - chart_scatter.png       : scatter roundtrips vs duration with regression
  - chart_timeline.png      : per-run timeline of cumulative time vs roundtrips
"""
from __future__ import annotations
import argparse
import csv
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_csv(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            r["items"] = int(r["items"])
            r["roundtrips"] = int(r["roundtrips"])
            r["duration_ms"] = int(r["duration_ms"])
            rows.append(r)
    return rows


def chart_bar(metric: str, ylabel: str, rows, out: Path):
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["workload"]].append(r[metric])
    labels = list(grouped.keys())
    avgs = [statistics.mean(grouped[k]) for k in labels]
    mins = [min(grouped[k]) for k in labels]
    maxs = [max(grouped[k]) for k in labels]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, avgs, color=["#d9534f", "#5cb85c"])
    for b, mn, mx, av in zip(bars, mins, maxs, avgs):
        ax.errorbar(b.get_x() + b.get_width() / 2, av,
                    yerr=[[av - mn], [mx - av]], fmt="none", ecolor="black", capsize=6)
        ax.text(b.get_x() + b.get_width() / 2, av, f"{av:,.0f}",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} per workload (mean of {len(rows)//len(labels)} runs)")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"wrote {out}")


def chart_scatter(rows, out: Path):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    colors = {"chatty": "#d9534f", "chunky": "#5cb85c"}
    for w in sorted({r["workload"] for r in rows}):
        xs = [r["roundtrips"] for r in rows if r["workload"] == w]
        ys = [r["duration_ms"] for r in rows if r["workload"] == w]
        ax.scatter(xs, ys, color=colors.get(w, "gray"), label=w, s=80)
    ax.set_xlabel("Round-trips (count)")
    ax.set_ylabel("Total duration (ms)")
    ax.set_title("Round-trips vs total time — chatty vs chunky")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"wrote {out}")


def chart_per_run(rows, out: Path):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.35
    workloads = sorted({r["workload"] for r in rows})
    runs_per = max(sum(1 for r in rows if r["workload"] == w) for w in workloads)
    x = list(range(runs_per))
    for i, w in enumerate(workloads):
        wrows = [r for r in rows if r["workload"] == w]
        ys = [r["duration_ms"] for r in wrows]
        ax.bar([xi + i * width for xi in x], ys, width, label=w,
               color="#d9534f" if w == "chatty" else "#5cb85c")
    ax.set_xticks([xi + width / 2 for xi in x])
    ax.set_xticklabels([f"run {i+1}" for i in x])
    ax.set_ylabel("Duration (ms)")
    ax.set_title("Per-run duration")
    ax.legend()
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path,
                        help="results CSV produced by run_experiments.sh")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows = load_csv(args.csv)
    if not rows:
        print("no rows", file=sys.stderr)
        sys.exit(1)
    args.out.mkdir(parents=True, exist_ok=True)

    chart_bar("roundtrips", "Round-trips", rows, args.out / "chart_roundtrips.png")
    chart_bar("duration_ms", "Duration (ms)", rows, args.out / "chart_duration.png")
    chart_scatter(rows, args.out / "chart_scatter.png")
    chart_per_run(rows, args.out / "chart_per_run.png")

    # Print headline numbers
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["workload"]].append(r)
    print("\n=== HEADLINE ===")
    for w, rs in grouped.items():
        avg_rt = statistics.mean(r["roundtrips"] for r in rs)
        avg_d = statistics.mean(r["duration_ms"] for r in rs)
        print(f"{w:6s}: avg roundtrips={avg_rt:,.0f}  avg duration_ms={avg_d:,.0f}")
    if {"chatty", "chunky"} <= grouped.keys():
        c = statistics.mean(r["duration_ms"] for r in grouped["chatty"])
        k = statistics.mean(r["duration_ms"] for r in grouped["chunky"])
        if k > 0:
            print(f"\nchatty is {c/k:.1f}x slower than chunky for the same logical work.")


if __name__ == "__main__":
    main()
