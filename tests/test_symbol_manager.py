"""
Unit tests for SymbolManager.
"""

import pytest
import pandas as pd
from pathlib import Path
from src.symbol_manager import SymbolManager


def test_symbol_conversion():
    assert SymbolManager.to_yahoo_ticker("HPG") == "HPG.VN"
    assert SymbolManager.to_yahoo_ticker("vnm") == "VNM.VN"
    assert SymbolManager.to_yahoo_ticker("SSI.VN") == "SSI.VN"

    assert SymbolManager.from_yahoo_ticker("HPG.VN") == "HPG"
    assert SymbolManager.from_yahoo_ticker("VIC") == "VIC"


def test_security_type_classification():
    assert SymbolManager.classify_security_type("HPG") == "EQUITY"
    assert SymbolManager.classify_security_type("E1VFVN30") == "ETF"
    assert SymbolManager.classify_security_type("FUEVFVND") == "ETF"
    assert SymbolManager.classify_security_type("CFPT2001") == "WARRANT"
    assert SymbolManager.classify_security_type("VNINDEX") == "INDEX"
    assert SymbolManager.classify_security_type("AAA", "CHỨNG KHOÁN") == "EQUITY"


def test_load_from_csv(tmp_path):
    csv_file = tmp_path / "test_stocks.csv"
    csv_file.write_text(
        "symbol,name,exchange\n"
        "VNM,Vinamilk,HOSE\n"
        "SHB,SHB Bank,HNX\n"
        "BSR,Binh Son,UPCoM\n",
        encoding="utf-8"
    )

    mgr = SymbolManager(seed_file=csv_file)
    df = mgr.load_from_csv()
    assert len(df) == 3
    assert set(df["symbol"]) == {"VNM", "SHB", "BSR"}
    assert set(df["yahoo_ticker"]) == {"VNM.VN", "SHB.VN", "BSR.VN"}


def test_filter_symbols(tmp_path):
    csv_file = tmp_path / "test_filter.csv"
    csv_file.write_text(
        "symbol,name,exchange,status\n"
        "VNM,Vinamilk,HOSE,ACTIVE\n"
        "HPG,Hoa Phat,HOSE,ACTIVE\n"
        "SHB,SHB Bank,HNX,ACTIVE\n"
        "BSR,Binh Son,UPCoM,DELISTED\n",
        encoding="utf-8"
    )

    mgr = SymbolManager(seed_file=csv_file)
    mgr.load_from_csv()

    hose_active = mgr.filter_symbols(exchanges=["HOSE"], status="ACTIVE")
    assert len(hose_active) == 2
    assert {s["symbol"] for s in hose_active} == {"VNM", "HPG"}

    upcom_delisted = mgr.filter_symbols(exchanges=["UPCoM"], status="DELISTED")
    assert len(upcom_delisted) == 1
    assert upcom_delisted[0]["symbol"] == "BSR"
