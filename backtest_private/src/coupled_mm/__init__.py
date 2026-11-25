"""Backtester market makingu dla sprzężonych kontraktów energii."""

from .config import BacktestConfig, load_config
from .engine import BacktestEngine, BacktestResult

__all__ = ["BacktestConfig", "BacktestEngine", "BacktestResult", "load_config"]
__version__ = "0.1.0"

