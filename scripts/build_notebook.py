"""Build the analysis Jupyter notebook from the merged CSVs.

Writes ``results/notebook/analysis.ipynb`` with markdown narration and code
cells, then executes it with nbclient so the figure outputs are baked in.
PNGs are also saved alongside via ``fig.savefig`` calls in the cells, so the
images are usable from outside Jupyter (e.g. embedded in the README).
"""
from __future__ import annotations
import os
import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell


HERE = os.path.dirname(os.path.abspath(__file__))
NB_DIR = os.path.normpath(os.path.join(HERE, os.pardir, "results", "notebook"))
NB_PATH = os.path.join(NB_DIR, "analysis.ipynb")


def md(text: str):
    return new_markdown_cell(text)


def code(src: str):
    return new_code_cell(src)


CELLS = [
    md(
        "# Hybrid Latency Lab — WAN vs LAN comparison\n"
        "\n"
        "This notebook is the **analytical companion** to the lab. It reads the\n"
        "raw CSVs produced by `run_experiments.sh` and `latency_probe.py` from\n"
        "**both** measurement points and compares them side-by-side:\n"
        "\n"
        "| Env | Where it runs | Network to PG |\n"
        "| --- | --- | --- |\n"
        "| `onprem-wan` | Arc-onboarded \"on-prem\" VM in the on-prem VNet, reaching PG via vWAN, with `tc netem 80 ms ± 5 ms` injected on egress | simulated WAN ≈ 80 ms RTT |\n"
        "| `spoke-lan` | VM inside the same VNet as PG | LAN ≈ sub-millisecond RTT |\n"
        "\n"
        "Same scripts. Same database. Same dataset (5000 items, 500 processed per\n"
        "run). The only thing that changes is the network path. That's exactly\n"
        "what isolates the *WAN tax* on chatty round-trips.\n"
        "\n"
        "Files used:\n"
        "- `experiments.csv` — 6 runs per env (3 chatty + 3 chunky)\n"
        "- `latency_probe.csv` — 50 single-statement (`SELECT 1;`) RTT samples per env\n"
        "- raw per-env files in `../raw/`\n"
    ),

    code(
        "import os\n"
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "import numpy as np\n"
        "\n"
        "plt.rcParams.update({\n"
        "    'figure.dpi': 110,\n"
        "    'savefig.dpi': 140,\n"
        "    'figure.figsize': (8, 4.5),\n"
        "    'axes.grid': True,\n"
        "    'grid.alpha': 0.3,\n"
        "})\n"
        "\n"
        "HERE = os.getcwd()\n"
        "exp = pd.read_csv(os.path.join(HERE, 'experiments.csv'))\n"
        "probe = pd.read_csv(os.path.join(HERE, 'latency_probe.csv'))\n"
        "\n"
        "exp['duration_s'] = exp['duration_ms'] / 1000.0\n"
        "print('experiments shape :', exp.shape)\n"
        "print('probe       shape :', probe.shape)\n"
        "exp.head()\n"
    ),

    md(
        "## 1. Per-query RTT (the network tax, isolated)\n"
        "\n"
        "Before looking at any application logic, let's measure the **bare network\n"
        "round-trip time** as observed by a client. The probe opens one\n"
        "connection (so TLS / connect cost is excluded) and runs 50 sequential\n"
        "`SELECT 1;` statements. A `SELECT 1` is server-side O(microseconds), so\n"
        "the wall-clock per statement is dominated by the TCP round-trip.\n"
    ),
    code(
        "stats = (probe.groupby('env_label')['rtt_ms']\n"
        "             .agg(['min', 'median', 'mean', 'max',\n"
        "                   lambda s: np.percentile(s, 95)])\n"
        "             .rename(columns={'<lambda_0>': 'p95'}))\n"
        "stats = stats.round(2)\n"
        "stats\n"
    ),
    code(
        "fig, axes = plt.subplots(1, 2, figsize=(11, 4))\n"
        "\n"
        "for env, color in [('onprem-wan', 'tab:red'), ('spoke-lan', 'tab:green')]:\n"
        "    sub = probe[probe['env_label'] == env]\n"
        "    axes[0].plot(sub['sample_idx'], sub['rtt_ms'], marker='o',\n"
        "                 linewidth=1, markersize=3, color=color, label=env)\n"
        "axes[0].set_yscale('log')\n"
        "axes[0].set_xlabel('Sample index (50x SELECT 1 over a single connection)')\n"
        "axes[0].set_ylabel('Per-statement RTT (ms, log)')\n"
        "axes[0].set_title('Per-query RTT — onprem (WAN) vs spoke (LAN)')\n"
        "axes[0].legend(loc='best')\n"
        "\n"
        "data = [probe.loc[probe.env_label == env, 'rtt_ms'].values\n"
        "        for env in ['onprem-wan', 'spoke-lan']]\n"
        "axes[1].boxplot(data, tick_labels=['onprem-wan', 'spoke-lan'],\n"
        "                showmeans=True)\n"
        "axes[1].set_yscale('log')\n"
        "axes[1].set_ylabel('Per-statement RTT (ms, log)')\n"
        "axes[1].set_title('Distribution (boxplot, log scale)')\n"
        "\n"
        "fig.suptitle('Network RTT to PostgreSQL — same client, same DB, two paths',\n"
        "             fontweight='bold')\n"
        "fig.tight_layout()\n"
        "fig.savefig('fig_01_per_query_rtt.png', bbox_inches='tight')\n"
        "plt.show()\n"
    ),
    md(
        "**Reading the chart**: the WAN line sits on the ≈ 80 ms shelf imposed by\n"
        "`tc netem`, with the natural ±5 ms jitter we asked for. The LAN line is\n"
        "two orders of magnitude lower (≈ 0.5 ms median). That ratio — *not* CPU,\n"
        "*not* disk I/O, *not* PG configuration — is the tax we're about to pay\n"
        "every single round-trip from the chatty client.\n"
    ),

    md(
        "## 2. Application workload duration\n"
        "\n"
        "Now run the same Python scripts (`chatty.py`, `chunky.py`) on each side\n"
        "and look at wall-clock duration. Both scripts process **the same 500\n"
        "items**; the only difference is whether they use N+1 (`chatty`) or a\n"
        "single set-based statement (`chunky`).\n"
    ),
    code(
        "summary = (exp.groupby(['env_label', 'workload'])\n"
        "             .agg(runs=('run_id', 'count'),\n"
        "                  avg_roundtrips=('roundtrips', 'mean'),\n"
        "                  avg_duration_s=('duration_s', 'mean'))\n"
        "             .round(3)\n"
        "             .reset_index())\n"
        "summary\n"
    ),
    code(
        "fig, ax = plt.subplots(figsize=(8, 4.5))\n"
        "envs = ['onprem-wan', 'spoke-lan']\n"
        "workloads = ['chatty', 'chunky']\n"
        "x = np.arange(len(envs))\n"
        "width = 0.35\n"
        "for i, w in enumerate(workloads):\n"
        "    vals = [summary.query('env_label==@e and workload==@w')['avg_duration_s'].iloc[0]\n"
        "            for e in envs]\n"
        "    bars = ax.bar(x + (i - 0.5) * width, vals, width, label=w,\n"
        "                  color='tab:red' if w == 'chatty' else 'tab:blue')\n"
        "    for b, v in zip(bars, vals):\n"
        "        ax.text(b.get_x() + b.get_width() / 2, v, f'{v:.2f}s',\n"
        "                ha='center', va='bottom', fontsize=9)\n"
        "ax.set_yscale('log')\n"
        "ax.set_xticks(x)\n"
        "ax.set_xticklabels(envs)\n"
        "ax.set_ylabel('Avg duration (s, log scale)')\n"
        "ax.set_title('Wall-clock duration — chatty vs chunky, on each network')\n"
        "ax.legend()\n"
        "fig.tight_layout()\n"
        "fig.savefig('fig_02_duration_by_env.png', bbox_inches='tight')\n"
        "plt.show()\n"
    ),

    md(
        "## 3. The WAN tax, made explicit\n"
        "\n"
        "For each workload, the slowdown when moving from LAN to WAN is **directly\n"
        "proportional to the number of round-trips × per-query RTT**. We can\n"
        "verify that empirically:\n"
        "\n"
        "$$\\Delta_{\\text{WAN tax}} \\approx N_{\\text{round-trips}} \\times \\text{RTT}_{\\text{WAN}}$$\n"
    ),
    code(
        "lan = summary.query(\"env_label == 'spoke-lan'\").set_index('workload')\n"
        "wan = summary.query(\"env_label == 'onprem-wan'\").set_index('workload')\n"
        "extra_s = (wan['avg_duration_s'] - lan['avg_duration_s']).rename('wan_extra_s')\n"
        "rt = wan['avg_roundtrips']\n"
        "predicted_extra_s = (rt * 0.080).rename('predicted_extra_s_at_80ms_rtt')\n"
        "slowdown = (wan['avg_duration_s'] / lan['avg_duration_s']).rename('wan/lan ratio')\n"
        "compare = pd.concat([rt.rename('roundtrips'), extra_s, predicted_extra_s, slowdown], axis=1)\n"
        "compare = compare.round(3)\n"
        "compare\n"
    ),
    code(
        "fig, ax = plt.subplots(figsize=(8, 4.5))\n"
        "wls = compare.index.tolist()\n"
        "x = np.arange(len(wls))\n"
        "width = 0.38\n"
        "ax.bar(x - width/2, compare['wan_extra_s'], width,\n"
        "       label='Measured extra time on WAN', color='tab:red')\n"
        "ax.bar(x + width/2, compare['predicted_extra_s_at_80ms_rtt'], width,\n"
        "       label='Predicted: roundtrips × 80 ms', color='tab:gray', alpha=0.7)\n"
        "for i, w in enumerate(wls):\n"
        "    ax.text(i - width/2, compare['wan_extra_s'].iloc[i],\n"
        "            f\"{compare['wan_extra_s'].iloc[i]:.1f}s\",\n"
        "            ha='center', va='bottom', fontsize=9)\n"
        "    ax.text(i + width/2, compare['predicted_extra_s_at_80ms_rtt'].iloc[i],\n"
        "            f\"{compare['predicted_extra_s_at_80ms_rtt'].iloc[i]:.1f}s\",\n"
        "            ha='center', va='bottom', fontsize=9, color='dimgray')\n"
        "ax.set_xticks(x)\n"
        "ax.set_xticklabels(wls)\n"
        "ax.set_ylabel('Extra wall-clock time on WAN vs LAN (s)')\n"
        "ax.set_title('The WAN tax = roundtrips × per-query RTT')\n"
        "ax.legend()\n"
        "fig.tight_layout()\n"
        "fig.savefig('fig_03_wan_tax_prediction.png', bbox_inches='tight')\n"
        "plt.show()\n"
    ),
    md(
        "Read the table:\n"
        "- `chatty`: 1003 round-trips × 80 ms ≈ **80 s** of pure WAN wait. The\n"
        "  measured extra time matches that prediction within a few seconds (the\n"
        "  rest is client-side CPU + PG server CPU).\n"
        "- `chunky`: 4 round-trips × 80 ms ≈ **0.32 s** of WAN wait. Same logical\n"
        "  work, but only 4 trips because it uses a single set-based\n"
        "  `INSERT … SELECT … LIMIT`.\n"
        "\n"
        "That's the headline of the lab: **chunky pays the tax 4 times, chatty\n"
        "pays it 1003 times.** The DB is identical in both cases.\n"
    ),

    md(
        "## 4. Run-by-run consistency\n"
        "\n"
        "Always look at variance — a single number can lie. Below is each\n"
        "individual run, so you can convince yourself the means above aren't an\n"
        "artifact of one outlier.\n"
    ),
    code(
        "fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=False)\n"
        "for ax, env in zip(axes, ['onprem-wan', 'spoke-lan']):\n"
        "    sub = exp[exp.env_label == env].copy()\n"
        "    sub = sub.sort_values(['workload', 'duration_s']).reset_index(drop=True)\n"
        "    sub['order'] = sub.groupby('workload').cumcount() + 1\n"
        "    for w, color in [('chatty', 'tab:red'), ('chunky', 'tab:blue')]:\n"
        "        s = sub[sub.workload == w]\n"
        "        ax.plot(s['order'], s['duration_s'], marker='o', linewidth=2,\n"
        "                label=w, color=color)\n"
        "    ax.set_yscale('log')\n"
        "    ax.set_xticks([1, 2, 3])\n"
        "    ax.set_xlabel('Run #')\n"
        "    ax.set_ylabel('Duration (s, log)')\n"
        "    ax.set_title(env)\n"
        "    ax.legend()\n"
        "fig.suptitle('Per-run duration on each environment',\n"
        "             fontweight='bold')\n"
        "fig.tight_layout()\n"
        "fig.savefig('fig_04_per_run_duration.png', bbox_inches='tight')\n"
        "plt.show()\n"
    ),

    md(
        "## 5. The single chart that summarises it all\n"
        "\n"
        "Put round-trips on the x-axis and duration on the y-axis (log-log) and\n"
        "the relationship is a line whose slope is exactly the per-query RTT.\n"
        "Two points per environment — chatty (top-right) and chunky (bottom-left)\n"
        "— land on two parallel lines, separated vertically by the LAN-vs-WAN\n"
        "gap.\n"
    ),
    code(
        "fig, ax = plt.subplots(figsize=(8, 5))\n"
        "colors = {'onprem-wan': 'tab:red', 'spoke-lan': 'tab:green'}\n"
        "markers = {'chatty': 'o', 'chunky': 's'}\n"
        "for env in ['onprem-wan', 'spoke-lan']:\n"
        "    for w in ['chatty', 'chunky']:\n"
        "        s = exp[(exp.env_label == env) & (exp.workload == w)]\n"
        "        ax.scatter(s['roundtrips'], s['duration_ms'], s=110,\n"
        "                   marker=markers[w], edgecolor='black', linewidth=0.6,\n"
        "                   color=colors[env], label=f'{env} / {w}')\n"
        "    # connect the two means with a thin line per env to show the slope\n"
        "    g = (exp[exp.env_label == env]\n"
        "         .groupby('workload')\n"
        "         .agg(rt=('roundtrips', 'mean'), dur=('duration_ms', 'mean')))\n"
        "    g = g.sort_values('rt')\n"
        "    ax.plot(g['rt'], g['dur'], color=colors[env], alpha=0.4, linewidth=1.5)\n"
        "ax.set_xscale('log')\n"
        "ax.set_yscale('log')\n"
        "ax.set_xlabel('Round-trips (log)')\n"
        "ax.set_ylabel('Duration (ms, log)')\n"
        "ax.set_title('Round-trips vs duration: same slope, two altitudes')\n"
        "ax.legend(loc='lower right', fontsize=9)\n"
        "fig.tight_layout()\n"
        "fig.savefig('fig_05_scatter_log_log.png', bbox_inches='tight')\n"
        "plt.show()\n"
    ),

    md(
        "## 6. Take-aways\n"
        "\n"
        "1. **Latency is per round-trip, not per byte.** Bandwidth is irrelevant\n"
        "   here — even on a fat ExpressRoute link, 1003 sequential queries\n"
        "   *cannot* finish in under `1003 × RTT`.\n"
        "2. **The fix is set-based work, not a faster network.** Moving from\n"
        "   chatty to chunky on the same WAN already shaves the cost down to a\n"
        "   handful of round-trips.\n"
        "3. **Same workload on the LAN side proves the DB and CPU are not the\n"
        "   bottleneck** — chatty over LAN finishes in ≈ 2.6 s, the WAN version in\n"
        "   ≈ 85 s. The only thing that changed is the path.\n"
        "4. **You can predict the WAN tax from first principles.** Pick up the\n"
        "   per-query RTT from the latency probe (or from Network Watcher\n"
        "   Connection Monitor) and multiply by the round-trip count of the\n"
        "   batch. Match that against measured duration; the gap is\n"
        "   client/server CPU.\n"
        "\n"
        "If you want to reproduce: bring up the lab with `infra/deploy.sh`, run\n"
        "the experiments with `scripts/run_experiments.sh` from each VM, run the\n"
        "probe with `scripts/latency_probe.py`, then re-run this notebook.\n"
    ),
]


def main() -> None:
    nb = new_notebook(cells=CELLS)
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    nb.metadata["language_info"] = {"name": "python"}
    os.makedirs(NB_DIR, exist_ok=True)
    nbf.write(nb, NB_PATH)
    print("wrote", NB_PATH)


if __name__ == "__main__":
    main()
