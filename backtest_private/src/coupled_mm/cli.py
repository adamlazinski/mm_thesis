from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config
from .data import load_quotes, load_trades
from .engine import BacktestEngine, _jsonable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtest market makingu dwóch sprzężonych kontraktów energii."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if config.execution.fill_model == "trade_queue" and args.trades is None:
        raise SystemExit("fill_model=trade_queue requires --trades")

    quotes = load_quotes(args.quotes, config.instruments)
    trades = [] if args.trades is None else load_trades(args.trades, config.instruments)
    result = BacktestEngine(config).run([*quotes, *trades])
    result.write(args.output_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.config, args.output_dir / "effective_config.json")
    inputs = [args.config, args.quotes] + ([] if args.trades is None else [args.trades])
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": __version__,
        "schema_version": "energy_csv_v1",
        "python": platform.python_version(),
        "fill_model": config.execution.fill_model,
        "records": {"quotes": len(quotes), "trades": len(trades)},
        "event_range": {
            "first": min(event.timestamp for event in [*quotes, *trades]).isoformat(),
            "last": max(event.timestamp for event in [*quotes, *trades]).isoformat(),
        },
        "inputs": [
            {"name": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in inputs
        ],
    }
    with (args.output_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    print(json.dumps(_jsonable(result.summary), indent=2, ensure_ascii=False))
    return 0 if result.summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
