"""
Input/Output Utilities for Swings.
Allows Layer 1 to export swings to disk and Layer 2 to import them independently.
"""

import json
import csv
from pathlib import Path
from typing import List, Union
from common.models import Swing


def save_swings(swings: List[Swing], path: Union[str, Path]) -> None:
    """
    Export list of Swing objects to disk in CSV or JSON format.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.suffix.lower() == ".json":
        data = [s.to_dict() for s in swings]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        # Default to CSV
        fieldnames = [
            "swing_id",
            "swing_type",
            "extreme_price",
            "extreme_time",
            "confirmed_at",
            "atr_at_extreme",
            "threshold",
            "source_timeframe",
            "lag_bars",
            "vol_over_median",
            "pct_change",
            "index",
            "confirmed_at_index",
            "structure_label"
        ]
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in swings:
                row = s.to_dict()
                writer.writerow(row)


def load_swings(path: Union[str, Path]) -> List[Swing]:
    """
    Load list of Swing objects from disk (CSV or JSON).
    Independent of Layer 1 candle data.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Swings file not found at: {file_path}")

    swings: List[Swing] = []
    if file_path.suffix.lower() == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            for item in raw_data:
                swings.append(Swing.from_dict(item))
    else:
        # Default to CSV
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                swings.append(Swing.from_dict(row))

    return swings
