"""
RL Training Driver
-------------------
Trains a TabularQ or DQN market making agent over multiple days of tick data.

Training/eval split mirrors the classical experiments:
  IS  (train): Jun 11–27  (17 days)
  OOS (eval):  Jun 28–Jul 10  (13 days)

Usage
-----
    python scripts/train_rl.py --config experiments/39_link_rl/config_dqn.json

Config format
-------------
{
    "data_dir":          "data/real",
    "train_start":       "2025-06-11",
    "train_end":         "2025-06-27",
    "eval_start":        "2025-06-28",
    "eval_end":          "2025-07-10",
    "symbol":            "LINK",
    "output_dir":        "experiments/39_link_rl/results_dqn",
    "checkpoint_dir":    "experiments/39_link_rl/checkpoints_dqn",
    "agent":             "dqn",       // "tabular" or "dqn"

    "tick_size":         0.001,
    "order_size":        5.0,
    "max_inventory":     38.0,
    "daily_loss_limit":  25.0,
    "maker_fee":         0.0,
    "latency":           0.1,
    "quote_freq":        0.5,
    "vol_window":        120,
    "arrival_window":    60,
    "ewma_alpha":        0.9,
    "inventory_penalty": 0.02,

    "hidden_dim":        128,
    "lr":                3e-4,
    "discount":          0.99,
    "epsilon_start":     1.0,
    "epsilon_end":       0.05,
    "epsilon_decay":     0.999999,
    "batch_size":        256,
    "target_update":     200,
    "replay_capacity":   100000,

    "learning_rate":     0.05,

    "n_epochs":          50,
    "eval_every":        5,
    "save_every":        10,
    "seed":              42,
    "notes":             ""
}

Output
------
- checkpoints/<epoch>.pt or .npy
- results/train_log.csv    — per-epoch aggregate metrics
- results/eval_log.csv     — per-epoch OOS evaluation metrics
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hft_market_maker.data.loader import DataLoader
from hft_market_maker.environments.market_making_env import MarketMakingEnv
from hft_market_maker.extensions.reinforcement_learning import (
    TabularQLearning, DQNMarketMaker, N_ACTIONS, ACTION_NAMES
)


# ============================================================
# Helpers
# ============================================================

def find_day_files(data_dir: Path, start: date, end: date, symbol: str = "LINK"):
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


def evaluate(agent, env: MarketMakingEnv, n_days: int) -> dict:
    """Greedy evaluation on all eval days; returns aggregate stats."""
    orig_eps = getattr(agent, "epsilon", None)
    orig_train = getattr(agent, "train_mode", None)

    # Switch to greedy mode
    if orig_eps is not None:
        agent.epsilon = agent.epsilon_end if hasattr(agent, "epsilon_end") else 0.0
    if orig_train is not None:
        agent.train_mode = False

    pnls, wins, fills_list = [], [], []
    for _ in range(n_days):
        obs  = env.reset()
        done = False
        while not done:
            action = agent.select_action(obs)
            obs, _, done, _ = env.step(action)
        ep = env.episode_stats()
        pnls.append(ep.total_pnl)
        wins.append(1 if ep.total_pnl > 0 else 0)
        fills_list.append(ep.n_fills)

    # Restore training state
    if orig_eps is not None:
        agent.epsilon = orig_eps
    if orig_train is not None:
        agent.train_mode = orig_train

    pnls_a = np.array(pnls)
    sharpe = (float(pnls_a.mean() / pnls_a.std() * np.sqrt(365))
              if pnls_a.std() > 1e-9 else 0.0)
    return {
        "mean_pnl":   float(pnls_a.mean()),
        "total_pnl":  float(pnls_a.sum()),
        "sharpe":     sharpe,
        "win_rate":   float(np.mean(wins)),
        "mean_fills": float(np.mean(fills_list)),
        "n_days":     n_days,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="RL market making training")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    seed = cfg.get("seed", 42)
    np.random.seed(seed)
    random.seed(seed)
    try:
        import torch; torch.manual_seed(seed)
    except ImportError:
        pass

    data_dir = Path(cfg["data_dir"])
    symbol   = cfg.get("symbol", "LINK")
    out_dir  = Path(cfg["output_dir"])
    ckpt_dir = Path(cfg.get("checkpoint_dir", str(out_dir / "checkpoints")))
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "config.json", "w") as f:
        json.dump(cfg, f, indent=2)

    train_files = find_day_files(data_dir,
                                 date.fromisoformat(cfg["train_start"]),
                                 date.fromisoformat(cfg["train_end"]), symbol)
    eval_files  = find_day_files(data_dir,
                                 date.fromisoformat(cfg["eval_start"]),
                                 date.fromisoformat(cfg["eval_end"]),  symbol)

    print(f"Train days: {len(train_files)}   Eval days: {len(eval_files)}")
    print(f"Agent: {cfg.get('agent','dqn')}   Symbol: {symbol}")
    if cfg.get("notes"):
        print(f"Notes: {cfg['notes']}")

    train_env = MarketMakingEnv(train_files, cfg, shuffle=True)
    eval_env  = MarketMakingEnv(eval_files,  cfg, shuffle=False)

    agent_type = cfg.get("agent", "dqn")
    common_kw  = dict(
        tick_size        = cfg.get("tick_size", 0.001),
        order_size       = cfg["order_size"],
        max_inventory    = cfg["max_inventory"],
        daily_loss_limit = cfg.get("daily_loss_limit", 30.0),
        inventory_penalty = cfg.get("inventory_penalty", 0.05),
        epsilon_start    = cfg.get("epsilon_start", 1.0),
        epsilon_end      = cfg.get("epsilon_end", 0.05),
        epsilon_decay    = cfg.get("epsilon_decay", 0.9999),
    )

    if agent_type == "tabular":
        agent = TabularQLearning(
            **common_kw,
            learning_rate = cfg.get("learning_rate", 0.05),
            discount      = cfg.get("discount", 0.99),
        )
    else:
        agent = DQNMarketMaker(
            **common_kw,
            hidden_dim      = cfg.get("hidden_dim", 128),
            lr              = cfg.get("lr", 3e-4),
            discount        = cfg.get("discount", 0.99),
            batch_size      = cfg.get("batch_size", 256),
            target_update   = cfg.get("target_update", 200),
            replay_capacity = cfg.get("replay_capacity", 100_000),
            train_mode      = True,
        )

    n_epochs   = cfg.get("n_epochs",  50)
    eval_every = cfg.get("eval_every", 5)
    save_every = cfg.get("save_every", 10)

    train_log_path = out_dir / "train_log.csv"
    eval_log_path  = out_dir / "eval_log.csv"

    train_fields = ["epoch", "mean_pnl", "win_rate", "mean_fills", "epsilon", "mean_loss"]
    eval_fields  = ["epoch", "mean_pnl", "sharpe", "win_rate", "mean_fills", "n_days"]

    with open(train_log_path, "w", newline="") as f:
        csv.DictWriter(f, train_fields).writeheader()
    with open(eval_log_path, "w", newline="") as f:
        csv.DictWriter(f, eval_fields).writeheader()

    print(f"\n{'Epoch':>6}  {'TrainPnL':>9}  {'EvalPnL':>9}  "
          f"{'Sharpe':>7}  {'Win':>5}  {'Fills':>7}  {'ε':>8}")
    print("-" * 65)

    for epoch in range(1, n_epochs + 1):
        # ── Training pass over all IS days ──────────────────────────────
        ep_pnls, ep_wins, ep_fills, ep_losses = [], [], [], []

        for _ in range(len(train_files)):
            obs  = train_env.reset()
            done = False
            while not done:
                prev_obs = obs
                action   = agent.select_action(obs)
                obs, reward, done, info = train_env.step(action)
                agent.update(prev_obs, action, reward, obs, done)
                if hasattr(agent, "last_loss") and agent.last_loss is not None:
                    ep_losses.append(agent.last_loss)

            ep = train_env.episode_stats()
            ep_pnls.append(ep.total_pnl)
            ep_wins.append(1 if ep.total_pnl > 0 else 0)
            ep_fills.append(ep.n_fills)

        train_mean_pnl = float(np.mean(ep_pnls))
        train_win      = float(np.mean(ep_wins))
        eps            = getattr(agent, "epsilon", 0.0)
        mean_loss      = float(np.mean(ep_losses)) if ep_losses else 0.0

        with open(train_log_path, "a", newline="") as f:
            csv.DictWriter(f, train_fields).writerow({
                "epoch":      epoch,
                "mean_pnl":   f"{train_mean_pnl:.4f}",
                "win_rate":   f"{train_win:.4f}",
                "mean_fills": f"{np.mean(ep_fills):.1f}",
                "epsilon":    f"{eps:.6f}",
                "mean_loss":  f"{mean_loss:.6f}",
            })

        # ── Evaluation pass every N epochs ──────────────────────────────
        eval_str = ""
        ev = {}
        if epoch % eval_every == 0 or epoch == n_epochs:
            ev = evaluate(agent, eval_env, len(eval_files))
            eval_str = f"  {ev['mean_pnl']:>+9.2f}  {ev['sharpe']:>7.1f}"
            with open(eval_log_path, "a", newline="") as f:
                csv.DictWriter(f, eval_fields).writerow({
                    "epoch":      epoch,
                    "mean_pnl":   f"{ev['mean_pnl']:.4f}",
                    "sharpe":     f"{ev['sharpe']:.2f}",
                    "win_rate":   f"{ev['win_rate']:.4f}",
                    "mean_fills": f"{ev['mean_fills']:.1f}",
                    "n_days":     ev["n_days"],
                })

        eval_pnl_str = f"{ev.get('mean_pnl', 0.0):>+9.2f}" if ev else f"{'—':>9}"
        sharpe_str   = f"{ev.get('sharpe', 0.0):>7.1f}" if ev else f"{'—':>7}"
        print(f"{epoch:>6}  {train_mean_pnl:>+9.2f}  {eval_pnl_str}  "
              f"{sharpe_str}  {train_win:>5.2f}  {np.mean(ep_fills):>7.0f}  {eps:>8.4f}")

        # ── Checkpoint ──────────────────────────────────────────────────
        if epoch % save_every == 0 or epoch == n_epochs:
            ckpt_path = str(ckpt_dir / f"epoch_{epoch:03d}")
            if agent_type == "dqn":
                agent.save(ckpt_path + ".pt")
            else:
                agent.save(ckpt_path + ".npy")
            print(f"  → checkpoint saved: {ckpt_path}")

    print("\nTraining complete.")
    print(f"  Train log: {train_log_path}")
    print(f"  Eval log:  {eval_log_path}")


if __name__ == "__main__":
    main()
