# QTA Layer 3 — Phase 3 only: Reversal Setup Detector lifecycle

Phase 3 runs an **in-memory** point-in-time candidate replay. It does NOT write SQL, update a DB, call an upsert, or emit `LONG_SETUP`. The baseline Layer 1/2 files and original Phase 1/2 code/data are unchanged byte-for-byte.

## Replay / testing (Python 3.10+ plus upstream pandas)

From the ZIP root:

```bash
python reversal_setup_detector/tools/report_phase3.py > reports/layer3_phase3/DATA_RUN_LOG.txt 2>&1
python reversal_setup_detector/run_phase3_tests.py > LAYER3_PHASE3_TEST_LOG.txt 2>&1
```

Read `reports/layer3_phase3/candidate_comparison.csv` for the 4 baseline rows **under both** cross-session policies; `reports/layer3_phase3/TRUE_*_candidates_events.json` and `FALSE_*_candidates_events.json` hold detailed in-memory state/event replay. `reports/layer3_phase3/slot_counts_by_ticker.csv` and `daily_counts_by_ticker.csv` audit all 5 symbols and 56 trading days. `calendar_audit.json` records exact slot exceptions, calendar hashes, and limitations.

## Algorithm / PIT semantics

- Reuse `candles.analyze` and `ContextProvider` **without modifying Layer 1/2 or earlier Phase 1/2 artifacts**. Model: R1/R2/R3 strong/any/strong red with strict body>wicks on R1/R3. Context at available_at(R3): last two adjacent Major by EVER_CONFIRMED; preserve their IDs and check their state at all subsequent relevant Layer2 event boundaries.
- At each already-available candle, update active candidates **before** creating a candidate whose R3 is that candle. R3 itself is never candidate's first green. Check consecutive calendar slots, 5 **after** R3; Decimal ratio bounds 1.0–2.0 **inclusive**, choose first passing G. Fifth failure EXPIRED. Overlapping red triplets allowed, deterministic ID derived from ticker+timeframe+R1/R2/R3+rule_version.
- Event timeline orders Layer2 events before candles at an equal available_at. BROKEN of either **original** structure at the very timestamp of G confirmation causes INVALIDATED, rather than FOUND. A break *after* FOUND does not backdate a revocation.
- `window_crosses_session` denotes **planned full five-slot window** crossing a session/date boundary, even if an earlier BROKEN terminates the candidate. `observed_window_crosses_session` separately flags an actually processed/barrier boundary. `red_triplet_crosses_session` is tracked independently.
- False variant disallows a red triple crossing lunch at *creation* and invalidates a waiting candidate if its next tested slot enters a new session. New rule_version + config_hash for each policy, leaving legacy config unchanged. Session boundary is not a missing candle.
- `Calendar.verified=False` by design: the 16 regular observed candle labels per trading date are empirically inferred, not a verified provider trading-bar spec. The two anomalous 14:30 records on 2026-08-20 are explicitly included ONLY for VCB and SSI. The observed 14:45 bars are preserved. Official HOSE/HNX 31 Aug–2 Sep exchange holidays are removed from expected dates. Saturday 22 Aug did not trade. This calendar should **not** be generalized to an unseen period/ticker without a fresh audit.
- Calendar-time close = bar open + 15m, effective available_at = max(close, source availability). Historical snapshot upstream available_at is inferred from its pipeline; provider feed arrival latency, exact auction-session mapping, and an as-received history remain **unverified** (L3-D03 CONDITIONAL). The schedule itself was calibrated retrospectively; an original historical calendar as-known-by-source is not available. Do not infer transaction timing from FOUND.
- Historical source corrections require explicit versioned recomputation, not silent overwrites. A triplet whose upstream bars become available *after* R3's processing is diagnosed `LATE_TRIPLET_AVAILABILITY_NO_BACKDATE`; no setup is created retroactively. Phase 3 does not persist setup events (later phase).

## Scope and acceptance

AT10–AT18 use **SYNTHETIC** OHLCV and synthetic Layer2 event-history fixtures for exact boundary correctness. Three extra tests exercise **REAL SNAPSHOT** data and compare the two session policies, plus synthetic tests covering simultaneous BROKEN/G, gaps, overlapping candidates, deterministic replay, crossing. Previous 63 tests are rerun unchanged as regressions.

Open decisions: L3-D03 conditionally approved pending independent upstream timestamp/as-received verification; L3-D04 deferred pending formal calendar and cross-session policy. L3-D01/D02/D05 remain approved.
