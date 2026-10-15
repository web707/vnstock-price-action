"""
Symbol Manager Module for Vietnam Stock Market.
Handles loading, filtering, normalizing, and managing stock symbols across HOSE, HNX, and UPCoM.
"""

from typing import List, Dict, Optional, Union
from pathlib import Path
import pandas as pd
from src.config import settings
from src.import_logger import logger


class SymbolManager:
    """Manages the universe of Vietnam stock tickers."""

    SUPPORTED_EXCHANGES = {"HOSE", "HNX", "UPCOM"}

    def __init__(self, seed_file: Optional[Union[str, Path]] = None):
        self.seed_file = Path(seed_file) if seed_file else settings.default_symbols_file
        self.symbols_df: pd.DataFrame = pd.DataFrame()

    @staticmethod
    def to_yahoo_ticker(symbol: str) -> str:
        """Convert a standard Vietnam symbol (e.g. 'HPG') to Yahoo Finance ticker ('HPG.VN')."""
        clean_sym = symbol.strip().upper()
        if clean_sym.endswith(".VN"):
            return clean_sym
        return f"{clean_sym}.VN"

    @staticmethod
    def from_yahoo_ticker(ticker: str) -> str:
        """Extract root symbol from Yahoo ticker (e.g. 'HPG.VN' -> 'HPG')."""
        clean_ticker = ticker.strip().upper()
        if clean_ticker.endswith(".VN"):
            return clean_ticker[:-3]
        return clean_ticker

    @staticmethod
    def classify_security_type(symbol: str, raw_type: Optional[str] = None) -> str:
        """
        Classify security into EQUITY, ETF, WARRANT, INDEX, or OTHER.
        - Covered warrants in Vietnam usually start with 'C' followed by 7-8 alphanumeric chars (e.g., CFPT2001).
        - Indices: VNINDEX, HNXINDEX, UPCOMINDEX, VN30, etc.
        - ETFs: start with E1, FU (e.g., E1VFVN30, FUEVFVND).
        """
        sym = symbol.strip().upper()
        if raw_type:
            raw_upper = raw_type.strip().upper()
            if "ETF" in raw_upper:
                return "ETF"
            if "WARRANT" in raw_upper or "CHỨNG QUYỀN" in raw_upper:
                return "WARRANT"
            if "INDEX" in raw_upper or "CHỈ SỐ" in raw_upper:
                return "INDEX"

        if sym in {"VNINDEX", "HNXINDEX", "UPCOMINDEX", "VN30", "HNX30"}:
            return "INDEX"
        if sym.startswith(("E1", "FU")) and len(sym) >= 8:
            return "ETF"
        if len(sym) >= 8 and sym.startswith("C"):
            return "WARRANT"
        return "EQUITY"

    def load_from_csv(self, csv_path: Optional[Union[str, Path]] = None) -> pd.DataFrame:
        """
        Load symbols from a CSV file.
        Accepts standard column variations: symbol/ticker, name/company_name, exchange/san, etc.
        """
        target_path = Path(csv_path) if csv_path else self.seed_file
        if not target_path.exists():
            raise FileNotFoundError(f"Symbols CSV file not found at: {target_path}")

        logger.info(f"Loading stock symbols from CSV: {target_path}")
        df = pd.read_csv(target_path, encoding="utf-8")

        # Map column names flexibly without creating duplicate columns
        col_map = {}
        lower_cols = {col.lower().strip(): col for col in df.columns}
        
        # Determine symbol column
        for sym_candidate in ("symbol", "ticker", "ma_ck", "code"):
            if sym_candidate in lower_cols:
                col_map[lower_cols[sym_candidate]] = "symbol"
                break

        # Determine company name column (prefer name_vn, then name, company_name)
        for name_candidate in ("name_vn", "name", "company_name", "ten_cty"):
            if name_candidate in lower_cols:
                col_map[lower_cols[name_candidate]] = "company_name"
                break

        # Determine exchange column
        for ex_candidate in ("exchange", "san", "san_gd"):
            if ex_candidate in lower_cols:
                col_map[lower_cols[ex_candidate]] = "exchange"
                break

        # Determine security type column
        for type_candidate in ("security_type", "type", "loai_ck"):
            if type_candidate in lower_cols:
                col_map[lower_cols[type_candidate]] = "security_type"
                break

        # Determine status column
        for st_candidate in ("status", "trang_thai"):
            if st_candidate in lower_cols:
                col_map[lower_cols[st_candidate]] = "status"
                break

        df = df.rename(columns=col_map)

        if "symbol" not in df.columns:
            raise ValueError(f"CSV file at {target_path} missing required 'symbol' column.")

        # Standardize symbols
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        df = df[df["symbol"].str.len() > 0].drop_duplicates(subset=["symbol"]).copy()

        # Company name
        if "company_name" not in df.columns:
            df["company_name"] = df["symbol"]
        else:
            df["company_name"] = df["company_name"].fillna(df["symbol"]).astype(str).str.strip()

        # Exchange
        if "exchange" not in df.columns:
            df["exchange"] = "UNKNOWN"
        else:
            df["exchange"] = (
                df["exchange"]
                .fillna("UNKNOWN")
                .astype(str)
                .str.strip()
                .str.upper()
                .replace({"UPCOM": "UPCoM", "HOSE": "HOSE", "HNX": "HNX"})
            )

        # Classify Security Type if missing
        if "security_type" not in df.columns:
            df["security_type"] = df["symbol"].apply(self.classify_security_type)
        else:
            df["security_type"] = df.apply(
                lambda r: self.classify_security_type(r["symbol"], r["security_type"]), axis=1
            )

        # Status
        if "status" not in df.columns:
            df["status"] = "ACTIVE"
        else:
            df["status"] = df["status"].fillna("ACTIVE").astype(str).str.strip().str.upper()

        # Yahoo Ticker
        df["yahoo_ticker"] = df["symbol"].apply(self.to_yahoo_ticker)
        df["source"] = f"CSV:{target_path.name}"

        self.symbols_df = df
        logger.info(f"Loaded {len(self.symbols_df)} valid symbols from {target_path.name}")
        return self.symbols_df

    def filter_symbols(
        self,
        exchanges: Optional[List[str]] = None,
        security_types: Optional[List[str]] = None,
        status: Optional[str] = "ACTIVE",
        symbols: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Filter symbols according to specific criteria and return as records list.
        """
        if self.symbols_df.empty:
            self.load_from_csv()

        df = self.symbols_df.copy()

        if symbols:
            # Clean given symbols
            clean_targets = {self.from_yahoo_ticker(s) for s in symbols}
            df = df[df["symbol"].isin(clean_targets)]

        if exchanges:
            # Case-insensitive exchange match
            norm_exchanges = {e.upper() for e in exchanges}
            df = df[df["exchange"].str.upper().isin(norm_exchanges)]

        if security_types:
            norm_types = {t.upper() for t in security_types}
            df = df[df["security_type"].str.upper().isin(norm_types)]

        if status:
            df = df[df["status"].str.upper() == status.upper()]

        if limit and limit > 0:
            df = df.head(limit)

        return df.to_dict(orient="records")

    def parse_symbol_inputs(self, symbol_input: Union[str, List[str]]) -> List[Dict]:
        """
        Parse user-specified symbol input strings (e.g. 'HPG,VNM,SSI' or ['HPG.VN', 'VIC']).
        If already in loaded symbols_df, reuses company_name and exchange; otherwise generates metadata.
        """
        if isinstance(symbol_input, str):
            raw_list = [s.strip() for s in symbol_input.split(",") if s.strip()]
        else:
            raw_list = [s.strip() for s in symbol_input if s.strip()]

        records = []
        for item in raw_list:
            sym = self.from_yahoo_ticker(item)
            ticker = self.to_yahoo_ticker(sym)
            sec_type = self.classify_security_type(sym)

            # Match against existing df if available
            if not self.symbols_df.empty and sym in self.symbols_df["symbol"].values:
                match = self.symbols_df[self.symbols_df["symbol"] == sym].iloc[0]
                records.append(match.to_dict())
            else:
                records.append({
                    "symbol": sym,
                    "yahoo_ticker": ticker,
                    "company_name": sym,
                    "exchange": "HOSE",  # default assumption if unspecified
                    "security_type": sec_type,
                    "status": "ACTIVE",
                    "source": "MANUAL_INPUT"
                })
        return records
