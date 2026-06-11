"""
Re-evaluate exp-58 RL policies on the CORRECTED engine (exp 62, option B).
=========================================================================
Loads each trained exp-58 greedy policy (epoch-200 tabular / epoch-060 DQN) and
re-runs it on the corrected engine (marketable-on-arrival = taker; commit 24a687f)
over the same train=eval days (LINK Apr 1-3 2026). Honest arms get the 4.5 bps
taker fee; the control (idealized inside-spread artifact) keeps fee=0.

This shows whether the same policies still hold up once latency-adverse taker fills
and the taker fee are modeled — without a multi-hour retrain.

Run:
    python experiments/62_engine_fix_reruns/eval_rl_corrected.py
"""
from __future__ import annotations
import json, sys
from datetime import date, timedelta
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hft_market_maker.environments.market_making_env import MarketMakingEnv
from hft_market_maker.extensions.reinforcement_learning import (
    TabularQLearning, DQNMarketMaker, ACTION_SPACES)

DATA = ROOT / "data" / "real"
OUT = Path("experiments/62_engine_fix_reruns/results")
EXP58 = ROOT / "experiments" / "58_rl_honest_overfit"

ARMS = [
    ("control_tabular",      "tabular", "epoch_200.npy", 0.0),       # idealized artifact
    ("honest_tabular",       "tabular", "epoch_200.npy", 0.00045),
    ("honest_tabular_qf05",  "tabular", "epoch_200.npy", 0.00045),
    ("honest_dqn",           "dqn",     "epoch_060.pt",  0.00045),
]


def day_files(symbol, start, end):
    out = []
    cur = start
    while cur <= end:
        ds = cur.strftime("%Y-%m-%d")
        t = DATA / f"trades_{symbol}_{ds}.parquet"
        q = DATA / f"quotes_{symbol}_{ds}.parquet"
        if t.exists() and q.exists():
            out.append((str(t), str(q)))
        cur += timedelta(days=1)
    return out


def ob_files(dfiles, symbol):
    res = []
    for tp, _ in dfiles:
        ds = Path(tp).stem.split("_")[-1]
        ob = DATA / f"orderbooks_{symbol}_{ds}.parquet"
        res.append(str(ob) if ob.exists() else None)
    return res


def build_agent(cfg, atype, action_params):
    kw = dict(tick_size=cfg.get("tick_size", 0.001), order_size=cfg["order_size"],
              max_inventory=cfg["max_inventory"], daily_loss_limit=cfg.get("daily_loss_limit", 30.0),
              inventory_penalty=cfg.get("inventory_penalty", 0.05),
              epsilon_start=0.0, epsilon_end=0.0, epsilon_decay=1.0, action_params=action_params)
    if atype == "tabular":
        return TabularQLearning(**kw, learning_rate=cfg.get("learning_rate", 0.1),
                                discount=cfg.get("discount", 0.99))
    return DQNMarketMaker(**kw, hidden_dim=cfg.get("hidden_dim", 128), lr=cfg.get("lr", 3e-4),
                          discount=cfg.get("discount", 0.99), train_mode=False)


def greedy_eval(agent, env, n_days):
    agent.epsilon = 0.0
    if hasattr(agent, "train_mode"):
        agent.train_mode = False
    pnls = []
    for _ in range(n_days):
        obs = env.reset(); done = False
        while not done:
            a = agent.select_action(obs)
            obs, _, done, _ = env.step(a)
        pnls.append(env.episode_stats().total_pnl)
    return np.array(pnls)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("Re-eval exp-58 policies on CORRECTED engine (LINK Apr 1-3, greedy)")
    print(f"  {'arm':>22} | {'orig ep200':>10} | {'corrected':>10} | {'taker_fee':>9}")
    rows = []
    # original committed epoch-200 eval means (from exp 58 eval logs)
    orig = {"control_tabular": 28.93, "honest_tabular": 1.24,
            "honest_tabular_qf05": 0.41, "honest_dqn": 0.15}
    for arm, atype, ckpt, tf in ARMS:
        cfg = json.load(open(EXP58 / f"config_{arm}.json"))
        cfg["taker_fee"] = tf
        cfg["data_dir"] = "data/real"
        ap = ACTION_SPACES[cfg.get("action_space", "link")][0]
        agent = build_agent(cfg, atype, ap)
        agent.load(str(EXP58 / f"checkpoints_{arm}" / ckpt))
        dfiles = day_files(cfg.get("symbol", "LINK"),
                           date.fromisoformat(cfg["eval_start"]),
                           date.fromisoformat(cfg["eval_end"]))
        env = MarketMakingEnv(dfiles, cfg, shuffle=False,
                              orderbook_files=ob_files(dfiles, cfg.get("symbol", "LINK")),
                              action_params=ap)
        p = greedy_eval(agent, env, len(dfiles))
        rows.append({"arm": arm, "taker_fee": tf, "orig_ep200": orig.get(arm),
                     "corrected_mean": round(float(p.mean()), 2),
                     "corrected_perday": [round(x, 2) for x in p.tolist()]})
        print(f"  {arm:>22} | {orig.get(arm, float('nan')):>+10.2f} | {p.mean():>+10.2f} | {tf:>9.5f}")
    json.dump(rows, open(OUT / "eval_rl_corrected.json", "w"), indent=2)
    print(f"\nSaved -> {OUT / 'eval_rl_corrected.json'}")


if __name__ == "__main__":
    main()
