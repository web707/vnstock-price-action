"""
Layer 2 — Market Structure Builder.
Consumes ONLY swing points (from file or list) without reading candlesticks.
Does NOT import from Layer 1.
Implements:
- Validation: checks unique swing_id, alternation, valid prices.
- Step A: Historical labelling (HH, HL, LH, LL, EH, EL).
- Step B: Structural segmentation and classification based on Draft Bruni Rules.
- get_last_two_confirmed(): retrieves two consecutive confirmed structures without skipping intermediate structures.
"""

import logging
from typing import List, Optional, Tuple, Dict, Any, Union
from pathlib import Path

from common.models import Swing, MarketStructure
from common.io import load_swings
from common.table_formatter import find_repeating_cycle
from structure_builder.rules import classify_segment, RULE_VERSION

logger = logging.getLogger("structure_builder")


class MarketStructureBuilder:
    """
    Market Structure Builder (Layer 2).
    """

    def __init__(
        self,
        bear_after_up_is_unclear: bool = True,
        rule_version: str = RULE_VERSION
    ):
        self.bear_after_up_is_unclear = bear_after_up_is_unclear
        self.rule_version = rule_version
        self.validation_logs: List[Dict[str, Any]] = []

    def validate_swings(self, swings: List[Swing]) -> List[Swing]:
        """
        Validates incoming swings:
        - Unique swing_id
        - Valid prices (> 0)
        - Valid swing_type (HIGH or LOW)
        - Strict HIGH-LOW alternation
        Logs DUPLICATE_SWING or INVALID_SWING_SEQUENCE without silent mutation.
        Returns filtered list of strictly valid swings (excluding duplicates).
        """
        if not swings:
            return []

        valid_swings: List[Swing] = []
        seen_ids = set()
        prev_type = None

        for s in swings:
            # Check ID uniqueness
            if s.swing_id in seen_ids:
                msg = f"Phát hiện swing trùng lặp swing_id={s.swing_id} tại {s.extreme_time}"
                logger.warning(msg)
                self.validation_logs.append({
                    "reason_code": "DUPLICATE_SWING",
                    "swing_id": s.swing_id,
                    "message": msg
                })
                continue  # KHÔNG tạo cấu trúc từ bản ghi trùng

            seen_ids.add(s.swing_id)

            # Check price validity
            if s.extreme_price <= 0:
                msg = f"Giá swing không hợp lệ: {s.extreme_price} (swing_id={s.swing_id})"
                logger.error(msg)
                self.validation_logs.append({
                    "reason_code": "INVALID_PRICE",
                    "swing_id": s.swing_id,
                    "message": msg
                })
                continue

            # Check swing type
            if s.swing_type not in ("HIGH", "LOW"):
                msg = f"Loại swing không hợp lệ: {s.swing_type} (swing_id={s.swing_id})"
                logger.error(msg)
                self.validation_logs.append({
                    "reason_code": "INVALID_SWING_TYPE",
                    "swing_id": s.swing_id,
                    "message": msg
                })
                continue

            # Check alternation
            if prev_type is not None and s.swing_type == prev_type:
                msg = f"Mất tính luân phiên HIGH-LOW: hai swing {prev_type} liên tiếp (swing_id={s.swing_id})"
                logger.warning(msg)
                self.validation_logs.append({
                    "reason_code": "INVALID_SWING_SEQUENCE",
                    "swing_id": s.swing_id,
                    "message": msg
                })
                # We record the log but keep it or discard according to strict sequence
                continue

            prev_type = s.swing_type
            valid_swings.append(s)

        return valid_swings

    def assign_structure_labels(self, swings: List[Swing]) -> List[Swing]:
        """
        Step A — Descriptive Market Structure Labelling:
        Compares each swing to the most recent swing OF THE SAME TYPE:
        - New High > Prev High * 1.001 -> HH
        - New High < Prev High * 0.999 -> LH
        - Otherwise -> EH (Equal High)
        - New Low > Prev Low * 1.001 -> HL
        - New Low < Prev Low * 0.999 -> LL
        - Otherwise -> EL (Equal Low)
        First swing of each type has no label (None).
        Computed over entire history.
        """
        prev_high: Optional[Swing] = None
        prev_low: Optional[Swing] = None

        for s in swings:
            if s.swing_type == "HIGH":
                if prev_high is None:
                    s.structure_label = None
                elif s.extreme_price > prev_high.extreme_price * 1.001:
                    s.structure_label = "HH"
                elif s.extreme_price < prev_high.extreme_price * 0.999:
                    s.structure_label = "LH"
                else:
                    s.structure_label = "EH"
                prev_high = s
            else:  # LOW
                if prev_low is None:
                    s.structure_label = None
                elif s.extreme_price > prev_low.extreme_price * 1.001:
                    s.structure_label = "HL"
                elif s.extreme_price < prev_low.extreme_price * 0.999:
                    s.structure_label = "LL"
                else:
                    s.structure_label = "EL"
                prev_low = s

        return swings

    def segment_and_classify(self, swings: List[Swing]) -> List[MarketStructure]:
        """
        Step B — Segmentation and Classification (Draft Bruni Rules):
        - Direction: BULL (HH, HL), BEAR (LH, LL). EH/EL are neutral.
        - Segment = consecutive swings of the same direction.
        - Start swing of next structure is the end swing of the previous structure.
        - Labels of structure are labels of swings in (start, end].
        - Evaluates status (CONFIRMED, FORMING, UNCLEAR).
        """
        if len(swings) < 2:
            return []

        # Find the first directional swing (BULL or BEAR)
        first_dir_idx = -1
        first_dir = None
        for i, s in enumerate(swings):
            if s.structure_label in ("HH", "HL"):
                first_dir_idx = i
                first_dir = "BULL"
                break
            elif s.structure_label in ("LH", "LL"):
                first_dir_idx = i
                first_dir = "BEAR"
                break

        if first_dir_idx == -1:
            return []

        # The anchor swing is the swing immediately preceding the first directional swing
        # (or index 0 if it's the very first)
        start_idx = max(0, first_dir_idx - 1)
        current_dir = first_dir
        current_segment_swings: List[Swing] = []

        raw_segments: List[Dict[str, Any]] = []

        for i in range(first_dir_idx, len(swings)):
            s = swings[i]
            lbl = s.structure_label

            if lbl in ("HH", "HL"):
                swing_dir = "BULL"
            elif lbl in ("LH", "LL"):
                swing_dir = "BEAR"
            else:
                swing_dir = "NEUTRAL"

            if swing_dir == "NEUTRAL":
                # Neutral (EH/EL) does not cut segment, included in range
                current_segment_swings.append(s)
                continue

            if swing_dir == current_dir:
                current_segment_swings.append(s)
            else:
                # Direction changed! Close previous segment at the previous swing
                prev_swing_idx = i - 1
                raw_segments.append({
                    "start_idx": start_idx,
                    "end_idx": prev_swing_idx,
                    "direction": current_dir,
                    "swings": list(current_segment_swings),
                    "is_open": False
                })

                # Start new segment: starts at the end swing of previous segment
                start_idx = prev_swing_idx
                current_dir = swing_dir
                current_segment_swings = [s]

        # The last segment remains open (FORMING)
        if current_segment_swings:
            raw_segments.append({
                "start_idx": start_idx,
                "end_idx": len(swings) - 1,
                "direction": current_dir,
                "swings": list(current_segment_swings),
                "is_open": True
            })

        # Classify each segment into MarketStructure
        structures: List[MarketStructure] = []
        prev_struct: Optional[MarketStructure] = None

        for idx, seg in enumerate(raw_segments, 1):
            seg_swings = seg["swings"]
            labels = [s.structure_label for s in seg_swings if s.structure_label]
            start_s = swings[seg["start_idx"]]
            end_s = swings[seg["end_idx"]]

            prev_type = prev_struct.structure_type if prev_struct else None
            prev_last_lbl = None
            if prev_struct and prev_struct.labels_sequence:
                prev_last_lbl = prev_struct.labels_sequence[-1]

            struct_type, status, reason, evidence = classify_segment(
                labels=labels,
                segment_direction=seg["direction"],
                prev_structure_type=prev_type,
                prev_last_label=prev_last_lbl,
                bear_after_up_is_unclear=self.bear_after_up_is_unclear
            )

            # If segment is still open at the end of the series, mark as FORMING
            if seg["is_open"]:
                status = "FORMING"

            confirmed_at = end_s.confirmed_at if status == "CONFIRMED" else None
            main_ev = evidence if evidence else find_repeating_cycle([l for l in labels if l not in ("EH", "EL")])

            ms = MarketStructure(
                structure_id=f"S{idx}",
                start_swing_id=start_s.swing_id,
                end_swing_id=end_s.swing_id,
                structure_type=struct_type,
                status=status,
                main_evidence=main_ev,
                confirmed_at=confirmed_at,
                invalidated_at=None,  # TODO: Unverified invalidation rules
                is_long_candidate=None,  # Unverified Long rules
                reason_code=reason,
                rule_version=self.rule_version,
                labels_sequence=labels
            )
            structures.append(ms)
            prev_struct = ms

        return structures

    def build(
        self,
        swings: List[Swing],
        as_of_time: Optional[str] = None
    ) -> Tuple[List[Swing], List[MarketStructure]]:
        """
        Executes full Layer 2 workflow on input swings:
        1. Filters by as_of_time (Zero Lookahead: confirmed_at <= as_of_time).
        2. Validates sequence and uniqueness.
        3. Step A: Assigns structure labels.
        4. Step B: Segments and classifies structures.
        """
        # 1. Zero Lookahead Filter
        if as_of_time is not None:
            active_swings = [
                s for s in swings
                if str(s.confirmed_at) <= str(as_of_time)
            ]
        else:
            active_swings = list(swings)

        # 2. Validation
        valid_swings = self.validate_swings(active_swings)

        # 3. Step A: Labelling
        labelled_swings = self.assign_structure_labels(valid_swings)

        # 4. Step B: Segmentation & Classification
        structures = self.segment_and_classify(labelled_swings)

        return labelled_swings, structures

    def build_from_file(
        self,
        file_path: Union[str, Path],
        as_of_time: Optional[str] = None
    ) -> Tuple[List[Swing], List[MarketStructure]]:
        """
        Builds market structures directly from a saved swings file (CSV/JSON).
        Zero dependencies on Layer 1 code or raw candle data.
        """
        swings = load_swings(file_path)
        return self.build(swings, as_of_time=as_of_time)

    def get_last_two_confirmed(
        self,
        structures: List[MarketStructure]
    ) -> Tuple[str, Optional[List[MarketStructure]]]:
        """
        Retrieves the two most recent CONFIRMED structures that are strictly ADJACENT (liền kề),
        without skipping any intermediate structures (e.g. UNCLEAR or BROKEN).
        
        Returns:
        - ("OK", [struct_prev, struct_curr]) if 2 adjacent confirmed structures exist.
        - ("INSUFFICIENT_STRUCTURE", None) if fewer than 2 exist or if an UNCLEAR/BROKEN
          structure lies between them.
        """
        # Ignore open FORMING structure at the very end
        closed_structs = [st for st in structures if st.status != "FORMING"]
        if len(closed_structs) < 2:
            return ("INSUFFICIENT_STRUCTURE", None)

        last_1 = closed_structs[-1]
        last_2 = closed_structs[-2]

        if last_1.status == "CONFIRMED" and last_2.status == "CONFIRMED":
            return ("OK", [last_2, last_1])

        return ("INSUFFICIENT_STRUCTURE", None)
