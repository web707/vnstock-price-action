# Phase 3 reason codes

- `STRUCTURE_CANDIDATE_CREATED`: forming
- `STRUCTURE_RULE_NOT_MET`: geometry_failure
- `STRUCTURE_CONFIRMED`: confirmed
- `STRUCTURE_BROKEN`: broken
- `PROTECTED_LEVEL_VIOLATED_AT_AVAILABILITY`: pre_broken
- `PRICE_AT_AVAILABILITY_MISSING`: missing_price
- `BREAK_RULE_NOT_CONFIGURED`: break_not_configured

Dữ liệu: reason codes kế thừa Phase 1; CONFLICTING_CANDLE quarantine; DUPLICATE_CANDLE INFO. STRUCTURE_RULE_NOT_MET trong audit là INFO cho cửa sổ không đạt, không phải lỗi dữ liệu.
