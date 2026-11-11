# Module B — VN30 research replay

Run from the repository root with `python -X utf8 -m extensions.vn30_expansion.run_vn30`. The runner uses the 30 constituents in the HOSE July 2026 review and writes per-ticker and aggregate results to `reports/extensions/vn30/`. Treat this membership as specific to its effective date. It is unsuitable as a substitute for historical point-in-time membership.

The runner reads local `reports/layer1/<TICKER>_clean.csv` files. Use the historical snapshot format and dates covered by the Layer 3 empirical calendar. Run `python -X utf8 -m layer1_cli --help` for input and export options. Keep these datasets local unless you have redistribution rights. A clean clone reports `MISSING_15M_OHLCV` for each absent dataset.

The runner calls Layer 1 swing detection, the SFS Layer 2 event builder and the Layer 3 `L3_REVERSAL_V1` lifecycle. It uses the existing August–October 2026 empirical calendar. The Yahoo collector writes to a separate SQLite database. Using its data for point-in-time replay requires a provider-specific calendar and verified publication and timestamp semantics.

Run the public smoke test from the root with `python -X utf8 -m unittest extensions.vn30_expansion.test_vn30`.
