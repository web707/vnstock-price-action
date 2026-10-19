"""
Market Structure Classification Rules (Draft Bruni Rules).
Rule Version: draft-0.1-bruni-unverified

All classification rules are consolidated in this single file for easy verification,
adjustment, and testing. Each rule has a clear rule_id, description, inputs,
conditions, and outputs.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


RULE_VERSION = "draft-0.1-bruni-unverified"


@dataclass
class RuleDefinition:
    """Metadata describing a market structure classification rule."""
    rule_id: str
    description: str
    conditions_summary: str
    output_type: str


RULES_REGISTRY: Dict[str, RuleDefinition] = {
    "RULE_BULL_UP": RuleDefinition(
        rule_id="RULE_BULL_UP",
        description="Đoạn liên tiếp các nhãn BULL có cả HH và HL -> Phân loại UP",
        conditions_summary="has_hh and has_hl and all_bull",
        output_type="UP"
    ),
    "RULE_BEAR_DOWN": RuleDefinition(
        rule_id="RULE_BEAR_DOWN",
        description="Đoạn liên tiếp các nhãn BEAR có cả LH và LL (không đứng ngay sau UP) -> Phân loại DOWN",
        conditions_summary="has_lh and has_ll and all_bear and not preceded_by_up",
        output_type="DOWN"
    ),
    "RULE_BEAR_AFTER_UP_UNCLEAR": RuleDefinition(
        rule_id="RULE_BEAR_AFTER_UP_UNCLEAR",
        description="Ngoại lệ Bruni: Đoạn BEAR đứng ngay sau một cấu trúc UP -> Phân loại UNCLEAR",
        conditions_summary="has_lh and has_ll and preceded_by_up and bear_after_up_is_unclear",
        output_type="UNCLEAR"
    ),
    "RULE_INSUFFICIENT_LABELS": RuleDefinition(
        rule_id="RULE_INSUFFICIENT_LABELS",
        description="Đoạn không đủ cặp nhãn cấu trúc tối thiểu -> Phân loại UNCLEAR",
        conditions_summary="not (has_hh and has_hl) and not (has_lh and has_ll)",
        output_type="UNCLEAR"
    ),
}


def classify_segment(
    labels: List[str],
    segment_direction: str,
    prev_structure_type: Optional[str] = None,
    prev_last_label: Optional[str] = None,
    bear_after_up_is_unclear: bool = True
) -> Tuple[str, str, str, str]:
    """
    Classifies a sequence of swing labels in (start_swing, end_swing].
    
    Parameters:
    - labels: List of structural labels in the segment (excluding neutral EH/EL for evidence)
    - segment_direction: 'BULL' or 'BEAR'
    - prev_structure_type: 'UP', 'DOWN', 'UNCLEAR', or None (type of previous structure)
    - prev_last_label: The last label of the preceding structure (e.g. 'HL')
    - bear_after_up_is_unclear: Configurable flag reproducing Bruni exception
    
    Returns:
    - (structure_type, status, reason_code, main_evidence)
    """
    non_neutral = [lbl for lbl in labels if lbl in ("HH", "HL", "LH", "LL")]
    has_hh = "HH" in non_neutral
    has_hl = "HL" in non_neutral
    has_lh = "LH" in non_neutral
    has_ll = "LL" in non_neutral

    if segment_direction == "BULL":
        if has_hh and has_hl:
            return (
                "UP",
                "CONFIRMED",
                "TWO_LABELS_BULL_CONFIRMED",
                ""  # Will use cycle or joined labels
            )
        else:
            return (
                "UNCLEAR",
                "UNCLEAR",
                "STRUCTURE_RULE_NOT_MET",
                " + ".join(non_neutral) if non_neutral else "INSUFFICIENT_LABELS"
            )

    elif segment_direction == "BEAR":
        if has_lh and has_ll:
            # Check Exception: BEAR standing immediately after an UP structure
            if bear_after_up_is_unclear and prev_structure_type == "UP":
                anchor_lbl = prev_last_label or "HL"
                return (
                    "UNCLEAR",
                    "UNCLEAR",
                    "BEAR_AFTER_UP_UNCLEAR",
                    f"LH + LL xuất hiện sau {anchor_lbl}"
                )
            return (
                "DOWN",
                "CONFIRMED",
                "TWO_LABELS_BEAR_CONFIRMED",
                ""  # Will use cycle or joined labels
            )
        else:
            return (
                "UNCLEAR",
                "UNCLEAR",
                "STRUCTURE_RULE_NOT_MET",
                " + ".join(non_neutral) if non_neutral else "INSUFFICIENT_LABELS"
            )

    return (
        "UNCLEAR",
        "UNCLEAR",
        "STRUCTURE_RULE_NOT_MET",
        " + ".join(non_neutral) if non_neutral else "INSUFFICIENT_LABELS"
    )
