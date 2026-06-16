from .backtest import Backtest, BacktestResults
from .core.events import TradeEvent, QuoteEvent, FillEvent
from .core.market_state import MarketState, MicrostructureStats
from .core.order_manager import OrderManager
from .strategies.avellaneda_stoikov import AvellanedaStoikov, QuoteDecision
from .strategies.aggressiveness import (
    RuleBasedAggressiveness,
    VolatilityScaledAS,
    OFIAsymmetricAS,
    InventoryUrgencyAS,
    FullAggressivenessAS,
)
from .strategies.glft import GLFTMarketMaker
from .strategies.shifted_glft import ShiftedGLFTMarketMaker
from .strategies.shifted_glft_numerical import ShiftedGLFTNumerical
from .strategies.vol_inventory import VolInventoryMarketMaker
from .extensions.regime_detection import (
    RegimeDetector, RegimeAwareAS, Regime, RegimeFilter,
    OFIDirectedFilter, OBIDirectedFilter,
    VPINFilter, HourFilter, TradeSpikeFilter, DailyLossLimit,
    KyleLambdaFilter, DynamicSizeFilter, SpreadMultiplierFilter,
)
# Pre-import xgboost before torch to avoid macOS OpenMP dylib conflict
# (both torch and xgboost link libomp; xgboost must win the first-load race)
try:
    import xgboost as _xgb  # noqa: F401
except ImportError:
    pass

from .extensions.reinforcement_learning import TabularQLearning, DQNMarketMaker
from .data.loader import DataLoader, generate_synthetic_data
from .core.vol_guardrail import VolRiskManager, VolGuardrail, VolatilityComposite, VolEstimates, GuardrailState

__all__ = [
    "Backtest", "BacktestResults",
    "TradeEvent", "QuoteEvent", "FillEvent",
    "MarketState", "MicrostructureStats",
    "OrderManager",
    "AvellanedaStoikov", "QuoteDecision",
    "RuleBasedAggressiveness", "VolatilityScaledAS",
    "OFIAsymmetricAS", "InventoryUrgencyAS", "FullAggressivenessAS",
    "GLFTMarketMaker", "ShiftedGLFTMarketMaker", "ShiftedGLFTNumerical", "VolInventoryMarketMaker",
    "RegimeDetector", "RegimeAwareAS", "Regime", "RegimeFilter",
    "OFIDirectedFilter", "OBIDirectedFilter",
    "VPINFilter", "HourFilter", "TradeSpikeFilter", "DailyLossLimit",
    "KyleLambdaFilter", "DynamicSizeFilter", "SpreadMultiplierFilter",
    "TabularQLearning", "DQNMarketMaker",
    "DataLoader", "generate_synthetic_data",
    "VolRiskManager", "VolGuardrail", "VolatilityComposite", "VolEstimates", "GuardrailState",
]
