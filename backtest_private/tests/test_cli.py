import json
from pathlib import Path

from coupled_mm.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_example_cli_is_reproducible_and_writes_auditable_outputs(tmp_path: Path) -> None:
    args = [
        "--config",
        str(ROOT / "configs/example.json"),
        "--quotes",
        str(ROOT / "examples/data/quotes.csv"),
        "--trades",
        str(ROOT / "examples/data/trades.csv"),
        "--output-dir",
        str(tmp_path),
    ]

    assert main(args) == 0
    first = json.loads((tmp_path / "summary.json").read_text())
    assert first["status"] == "complete"
    assert first["net_pnl"] == 4.0
    assert first["pnl_identity_error"] == 0.0
    assert first["end_positions"] == {"POWER_1200": 0.0, "POWER_1230": 0.0}
    assert {path.name for path in tmp_path.iterdir()} == {
        "effective_config.json",
        "equity.csv",
        "fills.csv",
        "manifest.json",
        "orders.csv",
        "sessions.json",
        "summary.json",
    }

    second_dir = tmp_path / "second"
    args[-1] = str(second_dir)
    assert main(args) == 0
    second = json.loads((second_dir / "summary.json").read_text())
    assert second == first
