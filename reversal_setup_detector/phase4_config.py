"""Explicit owner-approved v1 operating contract, separate from immutable Phase1 baseline.

The Phase1 proof-of-concept config used the *same version string* with UNAPPROVED
revision metadata and a weekday template. It was never a persisted contract.
We do not overwrite that file. This carefully-scoped adapter validates all
Rules fields using a temporary validation-only version string, then restores
the mandated public L3_REVERSAL_V1 version for canonical SHA256/identity.
All persisted outputs pin the approved config hash and reject colliding hashes.
"""
from pathlib import Path
import json,copy
from .candles import Rules
APPROVED_PATH=Path(__file__).parent/'config/L3_REVERSAL_V1_PHASE4_APPROVED.json'
class ApprovedRules(Rules):
    def __init__(self):
        payload=json.loads(APPROVED_PATH.read_text(encoding='utf-8'))
        assert payload['rule_version']=='L3_REVERSAL_V1'
        assert payload['allow_cross_session_sequences'] is True
        assert payload['decision_status']['L3-D04']=='APPROVED'
        assert payload['decision_status']['L3-D03']=='CONDITIONALLY_APPROVED'
        assert payload['calendar_template']['verified'] is False
        temporary=copy.deepcopy(payload)
        temporary['rule_version']='L3_REVERSAL_V1_PHASE4_VALIDATION_ONLY'
        super().__init__(temporary)  # all existing Phase1 Rules validation
        self._c=copy.deepcopy(payload)
