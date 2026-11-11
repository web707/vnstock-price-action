"""Reusable Layer 1 API. Legacy models and IO are loaded only when requested."""
from .config import SwingDetectorConfig
from .atr import compute_wilder_atr,validate_and_clean_data,clean_data
from .detector import detect_swings,detect_swings_frame,detect_result,DetectionResult

def save_swings(swings,path):
    if hasattr(swings,"layer1_result"):
        from .io import export_result
        return export_result(swings.layer1_result,path)
    from common.io import save_swings as save
    return save(swings,path)

def load_swings(path):
    from common.io import load_swings as load
    return load(path)
