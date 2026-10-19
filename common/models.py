"""
Common Data Models for Layer 1 (Swing Detection) and Layer 2 (Market Structure Builder).
Independent of both layers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Union


@dataclass
class Swing:
    """
    Swing Extreme Representation from Layer 1.
    Strictly contains only peak/trough detection properties.
    Structural classification label (HH, HL, LH, LL, EH, EL) is assigned by Layer 2.
    """
    swing_id: int                            # STT / Unique incremental identifier (1, 2, 3...)
    swing_type: str                          # "HIGH" or "LOW"
    extreme_price: float                     # Price at extreme peak/trough
    extreme_time: str                        # Datetime of extreme candle (YYYY-MM-DD HH:MM:SS)
    confirmed_at: str                        # Datetime when extreme was confirmed (YYYY-MM-DD HH:MM:SS)
    atr_at_extreme: float                    # ATR(14) calculated at candidate candle
    threshold: float                         # Dynamic Reversal Threshold T_i = max(mult * ATR, 0.5% Price)
    source_timeframe: str = "15m"            # Source candle timeframe (e.g. 15m)
    lag_bars: int = 0                        # Number of bars between candidate and confirmation (confirmed_at_index - index)
    vol_over_median: float = 1.0             # Volume ratio compared to 20-candle rolling median
    pct_change: Optional[float] = None       # Percentage amplitude compared to immediately preceding swing
    index: int = 0                           # Bar index in candle series
    confirmed_at_index: int = 0              # Confirmation bar index in candle series
    structure_label: Optional[str] = None    # Market Structure label (HH, HL, LH, LL, EH, EL) assigned by Layer 2 Step A

    def to_dict(self) -> Dict[str, Any]:
        return {
            "swing_id": self.swing_id,
            "swing_type": self.swing_type,
            "extreme_price": float(self.extreme_price),
            "extreme_time": str(self.extreme_time),
            "confirmed_at": str(self.confirmed_at),
            "atr_at_extreme": float(self.atr_at_extreme) if self.atr_at_extreme is not None else None,
            "threshold": float(self.threshold) if self.threshold is not None else None,
            "source_timeframe": self.source_timeframe,
            "lag_bars": int(self.lag_bars),
            "vol_over_median": float(self.vol_over_median) if self.vol_over_median is not None else None,
            "pct_change": float(self.pct_change) if self.pct_change is not None else None,
            "index": int(self.index),
            "confirmed_at_index": int(self.confirmed_at_index),
            "structure_label": self.structure_label
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Swing":
        pct = d.get("pct_change")
        if pct is not None and str(pct).lower() not in ("none", "nan", ""):
            pct = float(pct)
        else:
            pct = None

        atr_val = d.get("atr_at_extreme")
        atr_val = float(atr_val) if (atr_val is not None and str(atr_val).lower() not in ("none", "nan", "")) else 0.0

        thresh = d.get("threshold")
        thresh = float(thresh) if (thresh is not None and str(thresh).lower() not in ("none", "nan", "")) else 0.0

        vol_ratio = d.get("vol_over_median")
        vol_ratio = float(vol_ratio) if (vol_ratio is not None and str(vol_ratio).lower() not in ("none", "nan", "")) else 1.0

        struct_lbl = d.get("structure_label")
        if struct_lbl is not None and str(struct_lbl).lower() in ("none", "nan", ""):
            struct_lbl = None

        return cls(
            swing_id=int(d["swing_id"]),
            swing_type=str(d["swing_type"]).upper(),
            extreme_price=float(d["extreme_price"]),
            extreme_time=str(d["extreme_time"]),
            confirmed_at=str(d["confirmed_at"]),
            atr_at_extreme=atr_val,
            threshold=thresh,
            source_timeframe=str(d.get("source_timeframe", "15m")),
            lag_bars=int(d.get("lag_bars", 0)),
            vol_over_median=vol_ratio,
            pct_change=pct,
            index=int(d.get("index", 0)),
            confirmed_at_index=int(d.get("confirmed_at_index", 0)),
            structure_label=struct_lbl
        )


@dataclass
class MarketStructure:
    """
    Market Structure Segment produced by Layer 2.
    Groups consecutive swings into structural segments according to Bruni rules.
    """
    structure_id: str                        # Structure identifier (e.g. S1, S2, S3...)
    start_swing_id: int                      # Starting swing ID (STT in Table 1)
    end_swing_id: int                        # Ending swing ID (STT in Table 1)
    structure_type: str                      # "UP", "DOWN", or "UNCLEAR"
    status: str                              # "CONFIRMED", "FORMING", "UNCLEAR", "BROKEN"
    main_evidence: str                       # Primary evidence string (e.g. "LH + LL", "HH + HL + HH")
    confirmed_at: Optional[str] = None       # Confirmation datetime
    invalidated_at: Optional[str] = None     # Invalidation datetime (TODO: Unverified Bruni rule, default None)
    is_long_candidate: Optional[bool] = None # Long candidacy (TODO: Unverified Long rule, default None)
    reason_code: str = "STRUCTURE_CONFIRMED" # Reason code explaining classification
    rule_version: str = "draft-0.1-bruni-unverified" # Active rule version
    labels_sequence: List[str] = field(default_factory=list) # List of swing labels in (start, end]
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "start_swing_id": self.start_swing_id,
            "end_swing_id": self.end_swing_id,
            "structure_type": self.structure_type,
            "status": self.status,
            "main_evidence": self.main_evidence,
            "confirmed_at": self.confirmed_at,
            "invalidated_at": self.invalidated_at,
            "is_long_candidate": self.is_long_candidate,
            "reason_code": self.reason_code,
            "rule_version": self.rule_version,
            "labels_sequence": list(self.labels_sequence),
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
