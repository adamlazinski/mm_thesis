"""
Greedy TabularQ Evaluation
---------------------------
Loads a TabularQ checkpoint (.npy) and evaluates it with epsilon=0 (pure greedy)
over any date range. Also generates a Q-table heatmap showing the dominant action
per (inventory, volatility) cell for each (momentum, spike) context.

Usage
-----
    python scripts/eval_tabular_greedy.py \\
        --config  experiments/39_link_rl/config_tabular.json \\
        --checkpoint experiments/39_link_rl/checkpoints_tabular/epoch_030.npy \\
        --output_dir experiments/39_link_rl/greedy_eval

    # Evaluate on a custom date range (e.g. Apr 2026)
    python scripts/eval_tabular_greedy.py \\
        --config  experiments/39_link_rl/config_tabular.json \\
        --checkpoint experiments/39_link_rl/checkpoints_tabular/epoch_030.npy \\
        --start 2026-04-01 --end 2026-04-30 \\
        --output_dir experiments/39_link_rl/greedy_eval_apr2026

Output
------
    <output_dir>/
        per_day.csv          per-day PnL, fills, win/loss
        summary.json         aggregate stats (mean PnL, Sharpe, win rate)
        qtable_heatmap.png   dominant action per (inv, vol) for each (mom, spike)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import deque
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hft_market_maker.environments.market_making_env import MarketMakingEnv
from hft_market_maker.extensions.reinforcement_learning import (
    TabularQLearning, N_ACTIONS, N_STATES,
    ACTION_NAMES, INV_BINS, VOL_BINS, MOM_BINS, SPIKE_BINS,
)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_day_files(data_dir: Path, start: date, end: date, symbol: str):
    files = []
    current = start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        t = data_dir / f"trades_{symbol}_{ds}.parquet"
        q = data_dir / f"quotes_{symbol}_{ds}.parquet"
        if t.exists() and q.exists():
            files.append((str(t), str(q)))
        current += timedelta(days=1)
    return files


def find_orderbook_files(data_dir: Path, day_files: list, symbol: str):
    result = []
    for trades_path, _ in day_files:
        ds = Path(trades_path).stem.split("_")[-1]
        ob = data_dir / f"orderbooks_{symbol}_{ds}.parquet"
        result.append(str(ob) if ob.exists() else None)
    return result


# ---------------------------------------------------------------------------
# Greedy rollout
# ---------------------------------------------------------------------------

def greedy_eval(agent: TabularQLearning, env: MarketMakingEnv,
                n_days: int) -> tuple[list[dict], dict]:
    """Run pure greedy (epsilon=0) over all days. Returns per-day rows + summary."""
    agent.epsilon = 0.0
    agent.epsilon_end = 0.0

    rows = []
    pnls = []
    for _ in range(n_days):
        obs  = env.reset()
        done = False
        while not done:
            action = agent.select_action(obs)
            obs, _, done, _ = env.step(action)
        ep = env.episode_stats()
        row = {
            "date":     env._current_date,
            "pnl":      round(ep.total_pnl, 4),
            "n_fills":  ep.n_fills,
            "win":      1 if ep.total_pnl > 0 else 0,
            "n_steps":  ep.n_steps,
            "halts":    ep.halts,
            "peak_inv": round(ep.peak_inventory, 3),
        }
        rows.append(row)
        pnls.append(ep.total_pnl)
        print(f"  {row['date']}  PnL={row['pnl']:>+8.2f}  fills={row['n_fills']:>6}  "
              f"halts={row['halts']:>5}  {'WIN' if row['win'] else 'LOSS'}")

    pnls_a = np.array(pnls)
    std = pnls_a.std()
    sharpe = float(pnls_a.mean() / std * np.sqrt(252)) if std > 1e-9 else 0.0
    summary = {
        "mean_pnl":   round(float(pnls_a.mean()), 4),
        "total_pnl":  round(float(pnls_a.sum()), 4),
        "std_pnl":    round(float(std), 4),
        "sharpe":     round(sharpe, 2),
        "win_rate":   round(float(np.mean([r["win"] for r in rows])), 4),
        "n_days":     n_days,
        "mean_fills": round(float(np.mean([r["n_fills"] for r in rows])), 1),
    }
    return rows, summary


# ---------------------------------------------------------------------------
# Q-table heatmap
# ---------------------------------------------------------------------------

# Action colour groupings for the heatmap legend
_ACTION_GROUPS = {
    "halt":         (0,  "#555555"),
    "inside":       (1,  "#2196F3"),   # blue
    "near":         (5,  "#4CAF50"),   # green
    "at":           (8,  "#FF9800"),   # orange
    "outside":      (12, "#F44336"),   # red
    "wide":         (16, "#9C27B0"),   # purple
}

# Map each action id to a group colour
def _action_color(action_id: int) -> str:
    groups = sorted(_ACTION_GROUPS.values(), key=lambda x: x[0], reverse=True)
    for start_id, color in groups:
        if action_id >= start_id:
            return color
    return "#999999"


def plot_qtable_heatmap(Q: np.ndarray, out_path: str) -> None:
    """
    Dominant-action heatmap.  Layout: 3 columns (mom bins: low/neutral/high)
    × 2 rows (spike bins: normal/spike).  Each cell is 5 (inv) × 4 (vol).
    """
    n_inv   = len(INV_BINS) + 1    # 5
    n_vol   = len(VOL_BINS) + 1    # 4
    n_mom   = len(MOM_BINS) + 1    # 3
    n_spike = len(SPIKE_BINS) + 1  # 2

    inv_labels   = ["large\nshort", "short", "flat", "long", "large\nlong"]
    vol_labels   = ["calm", "normal", "active", "spiky"]
    mom_labels   = ["bear\nmom", "neutral", "bull\nmom"]
    spike_labels = ["no spike", "spike"]

    fig, axes = plt.subplots(n_spike, n_mom, figsize=(14, 8),
                             constrained_layout=True)
    fig.suptitle("TabularQ — Dominant Action per State\n(epoch 030, ε=0)",
                 fontsize=13, fontweight="bold")

    # Build colour matrix for each panel
    for spike_b in range(n_spike):
        for mom_b in range(n_mom):
            ax = axes[spike_b][mom_b]
            grid_ids  = np.zeros((n_inv, n_vol), dtype=int)
            grid_vals = np.zeros((n_inv, n_vol))

            for inv_b in range(n_inv):
                for vol_b in range(n_vol):
                    s = inv_b * (n_vol * n_mom * n_spike) + vol_b * (n_mom * n_spike) + mom_b * n_spike + spike_b
                    best_a   = int(np.argmax(Q[s]))
                    best_val = float(np.max(Q[s]))
                    grid_ids[inv_b, vol_b]  = best_a
                    grid_vals[inv_b, vol_b] = best_val

            # Colour image
            color_grid = np.zeros((n_inv, n_vol, 3))
            for ii in range(n_inv):
                for vi in range(n_vol):
                    hex_c = _action_color(grid_ids[ii, vi])
                    r, g, b = int(hex_c[1:3],16)/255, int(hex_c[3:5],16)/255, int(hex_c[5:7],16)/255
                    color_grid[ii, vi] = [r, g, b]

            ax.imshow(color_grid, aspect="auto", origin="upper",
                      interpolation="nearest")

            # Annotate each cell with action name
            for ii in range(n_inv):
                for vi in range(n_vol):
                    name = ACTION_NAMES[grid_ids[ii, vi]]
                    short = name.replace("inside_", "in·").replace("outside_", "out·") \
                                .replace("near_", "nr·").replace("wide_", "w·") \
                                .replace("at_sym_patient","at·pat") \
                                .replace("outside_patient","out·pat") \
                                .replace("_sym_fast","·sf").replace("_sym","·s") \
                                .replace("_lean_bid","·lb").replace("_lean_ask","·la")
                    ax.text(vi, ii, short, ha="center", va="center",
                            fontsize=6, color="white", fontweight="bold")

            ax.set_xticks(range(n_vol))
            ax.set_xticklabels(vol_labels, fontsize=7)
            ax.set_yticks(range(n_inv))
            ax.set_yticklabels(inv_labels, fontsize=7)

            if spike_b == 0:
                ax.set_title(mom_labels[mom_b], fontsize=9, fontweight="bold")
            if mom_b == 0:
                ax.set_ylabel(spike_labels[spike_b], fontsize=9, fontweight="bold")
            if spike_b == n_spike - 1:
                ax.set_xlabel("Volatility regime", fontsize=8)

    # Legend
    patches = [mpatches.Patch(color=c, label=g)
               for g, (_, c) in _ACTION_GROUPS.items()]
    fig.legend(handles=patches, loc="lower center", ncol=len(patches),
               fontsize=8, title="Action group", title_fontsize=8,
               bbox_to_anchor=(0.5, -0.04))

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Q-table heatmap saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",     required=True,
                        help="Path to config_tabular.json")
    parser.add_argument("--checkpoint", default=None,
                        help="Path to .npy Q-table checkpoint "
                             "(default: checkpoints_tabular/epoch_030.npy)")
    parser.add_argument("--start",  default=None,
                        help="Eval start date YYYY-MM-DD (overrides config eval_start)")
    parser.add_argument("--end",    default=None,
                        help="Eval end date   YYYY-MM-DD (overrides config eval_end)")
    parser.add_argument("--symbol", default=None,
                        help="Symbol override (default: from config)")
    parser.add_argument("--output_dir", default=None,
                        help="Where to save results (default: <config output_dir>/greedy_eval)")
    parser.add_argument("--no_heatmap", action="store_true",
                        help="Skip Q-table heatmap generation")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    np.random.seed(cfg.get("seed", 42))

    data_dir  = Path(cfg["data_dir"])
    symbol    = args.symbol or cfg.get("symbol", "LINK")
    ckpt_path = args.checkpoint or str(
        Path(cfg["checkpoint_dir"]) / "epoch_030.npy"
    )
    out_dir = Path(args.output_dir or (Path(cfg["output_dir"]).parent / "greedy_eval"))
    out_dir.mkdir(parents=True, exist_ok=True)

    eval_start = date.fromisoformat(args.start or cfg["eval_start"])
    eval_end   = date.fromisoformat(args.end   or cfg["eval_end"])

    print(f"Loading checkpoint: {ckpt_path}")
    agent = TabularQLearning(
        tick_size        = cfg.get("tick_size", 0.001),
        order_size       = cfg["order_size"],
        max_inventory    = cfg["max_inventory"],
        daily_loss_limit = cfg.get("daily_loss_limit", 30.0),
        inventory_penalty = cfg.get("inventory_penalty", 0.05),
        epsilon_start    = 0.0,
        epsilon_end      = 0.0,
        epsilon_decay    = 1.0,
        learning_rate    = 0.0,   # no learning during eval
        discount         = cfg.get("discount", 0.99),
    )
    agent.load(ckpt_path)
    agent.epsilon = 0.0

    print(f"Symbol: {symbol}  Eval: {eval_start} → {eval_end}")

    day_files = find_day_files(data_dir, eval_start, eval_end, symbol)
    if not day_files:
        print("ERROR: no data files found for the requested date range.")
        sys.exit(1)
    ob_files  = find_orderbook_files(data_dir, day_files, symbol)
    print(f"Days found: {len(day_files)}")

    env = MarketMakingEnv(day_files, cfg, shuffle=False, orderbook_files=ob_files)

    print(f"\n{'Date':>12}  {'PnL':>9}  {'Fills':>7}  {'Halts':>6}  Result")
    print("-" * 55)
    rows, summary = greedy_eval(agent, env, len(day_files))

    # Save per-day CSV
    csv_path = out_dir / "per_day.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nPer-day results saved: {csv_path}")

    # Save summary JSON
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*55}")
    print(f"  Period:     {eval_start} → {eval_end}")
    print(f"  Days:       {summary['n_days']}")
    print(f"  Mean PnL:   ${summary['mean_pnl']:>+.2f}/day")
    print(f"  Total PnL:  ${summary['total_pnl']:>+.2f}")
    print(f"  Std PnL:    ${summary['std_pnl']:.2f}")
    print(f"  Sharpe:     {summary['sharpe']:.1f}")
    print(f"  Win rate:   {summary['win_rate']*100:.0f}%")
    print(f"  Mean fills: {summary['mean_fills']:.0f}/day")
    print(f"  Summary:    {summary_path}")
    print(f"{'='*55}")

    # Q-table heatmap
    if not args.no_heatmap:
        heatmap_path = str(out_dir / "qtable_heatmap.png")
        plot_qtable_heatmap(agent.Q, heatmap_path)


if __name__ == "__main__":
    main()
