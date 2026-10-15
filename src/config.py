"""
Configuration module for Vietnam Stock Data Pipeline.
Loads environment variables from .env file and provides typed settings.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# Root directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from BASE_DIR if present
load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    # Oracle Database Settings
    oracle_user: str = os.getenv("ORACLE_USER", "")
    oracle_password: str = os.getenv("ORACLE_PASSWORD", "")
    oracle_dsn: str = os.getenv("ORACLE_DSN", "localhost:1521/XEPDB1")
    oracle_mode: str = os.getenv("ORACLE_MODE", "thin").lower()  # "thin" or "thick"
    oracle_client_lib_dir: str = os.getenv("ORACLE_CLIENT_LIB_DIR", "")
    oracle_wallet_location: str = os.getenv("ORACLE_WALLET_LOCATION", "")
    oracle_wallet_password: str = os.getenv("ORACLE_WALLET_PASSWORD", "")
    oracle_pool_min: int = int(os.getenv("ORACLE_POOL_MIN", "1"))
    oracle_pool_max: int = int(os.getenv("ORACLE_POOL_MAX", "5"))

    # Pipeline Settings
    yfinance_request_delay_sec: float = float(os.getenv("YFINANCE_REQUEST_DELAY_SEC", "0.35"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_backoff_factor: float = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
    db_batch_size: int = int(os.getenv("DB_BATCH_SIZE", "1000"))

    # File & Directory Paths
    default_symbols_file: Path = BASE_DIR / os.getenv("DEFAULT_SYMBOLS_FILE", "data/vietnam_stocks.csv")
    reports_dir: Path = BASE_DIR / "data" / "reports"
    state_dir: Path = BASE_DIR / "data" / "state"
    logs_dir: Path = BASE_DIR / "logs"
    schema_file: Path = BASE_DIR / "sql" / "schema.sql"

    def is_oracle_configured(self) -> bool:
        """Check whether minimum Oracle connection credentials are provided."""
        return bool(self.oracle_user.strip() and self.oracle_password.strip() and self.oracle_dsn.strip())

    def ensure_directories(self) -> None:
        """Ensure necessary output directories exist."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
settings.ensure_directories()
