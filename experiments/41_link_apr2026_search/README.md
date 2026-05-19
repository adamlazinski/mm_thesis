# Exp 41 — LINK April 2026 IS/OOS Search

## Workflow

**Step 1 — IS search (Apr 1–15)**
```bash
python scripts/random_search.py --config experiments/41_link_apr2026_search/search_config_is.json
```
Results → `search/41_link_apr2026_is.csv`. Take the top trial and paste its params into `config_oos.json`.

**Step 2 — OOS run (Apr 16–30)**
```bash
python scripts/run_daily.py --config experiments/41_link_apr2026_search/config_oos.json
python scripts/run_daily.py --config experiments/41_link_apr2026_search/config_oos.json --aggregate
```

Compare OOS mean_pnl against exp 40 baseline (zero-shot transfer).
