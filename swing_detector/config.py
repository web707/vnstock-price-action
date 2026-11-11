"""Layer 1 configuration; no trading/execution or Layer 2 rules."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class SwingDetectorConfig:
    timeframe: str = '15m'
    ticker: str | None = None
    atr_period: int = 14
    pivot_left: int = 3
    pivot_right: int = 3
    reversal_atr_mult: float = 2.0
    reversal_min_pct: float = .005
    min_bars_between_swings: int = 0
    volume_lookback: int = 20
    tie_rule: str = 'first'
    timezone: str = 'Asia/Ho_Chi_Minh'
    naive_timezone: str = 'Asia/Ho_Chi_Minh'
    timestamp_label: str = 'open'
    sessions: tuple = (('09:00','11:30'),('13:00','15:00'))
    ambiguous_bar_rule: str = 'defer'
    # Compatibility aliases used by the unchanged run_pipeline.py.
    swing_left: int | None = None
    swing_right: int | None = None
    reversal_mult: float | None = None
    min_reversal_pct: float | None = None

    def __post_init__(self):
        if self.ticker is not None:
            if not isinstance(self.ticker,str) or not self.ticker.strip():
                raise ValueError("ticker must be a nonempty string or None")
            object.__setattr__(self,"ticker",self.ticker.strip().upper())
        for alias, target in [('swing_left','pivot_left'),('swing_right','pivot_right'),
                              ('reversal_mult','reversal_atr_mult'),('min_reversal_pct','reversal_min_pct')]:
            if getattr(self,alias) is not None:
                object.__setattr__(self,target,getattr(self,alias))
        for key in ('atr_period','pivot_left','pivot_right','volume_lookback'):
            if not isinstance(getattr(self,key),int) or getattr(self,key)<1:
                raise ValueError(key+' must be a positive integer')
        if not isinstance(self.min_bars_between_swings,int) or self.min_bars_between_swings<0:
            raise ValueError('min_bars_between_swings must be a nonnegative integer')
        if self.timeframe!='15m' or self.tie_rule!='first' or self.ambiguous_bar_rule!='defer':
            raise ValueError('Supported: 15m, tie_rule=first, ambiguous_bar_rule=defer')
        if self.timestamp_label not in ('open','close'):
            raise ValueError('timestamp_label must be open or close')
        for key in ('reversal_atr_mult','reversal_min_pct'):
            if not math.isfinite(getattr(self,key)) or getattr(self,key)<0:
                raise ValueError(key+' must be finite and nonnegative')
        if self.reversal_atr_mult==0 and self.reversal_min_pct==0:
            raise ValueError('At least one reversal threshold must be positive')
