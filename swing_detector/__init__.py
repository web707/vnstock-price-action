"""
Layer 1 — Swing Point Detection Module.
Exclusively responsible for detecting swing high/low points from 15m OHLCV data.
Does NOT import from Layer 2.
"""

from swing_detector.detector import detect_swings, SwingDetectorConfig
from swing_detector.atr import compute_wilder_atr, validate_and_clean_data
from common.io import save_swings, load_swings

__all__ = [
    "detect_swings",
    "SwingDetectorConfig",
    "compute_wilder_atr",
    "validate_and_clean_data",
    "save_swings",
    "load_swings"
]
