"""Database connection helper + PostGIS smoke test.

Run the smoke test:
    python -m src.db
It connects using credentials from .env and prints the PostGIS version.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Load .env from the project root (one level up from src/).
load_dotenv()


def get_engine() -> Engine:
    """Build a SQLAlchemy engine from PG* environment variables (.env)."""
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "peage_invisible")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    # pool_pre_ping avoids stale-connection errors during long ingestion runs.
    return create_engine(url, pool_pre_ping=True, future=True)


def smoke_test() -> int:
    """Connect and print the PostGIS version. Returns a process exit code."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            version = conn.execute(text("SELECT postgis_version();")).scalar_one()
        print(f"PostGIS OK -> {version}")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface any connection/setup error clearly
        print(f"PostGIS smoke test FAILED: {exc}", file=sys.stderr)
        print(
            "Hints: is PostgreSQL running? did you copy .env.example to .env and set "
            "credentials? did you run `psql -f sql/00_init.sql` to enable PostGIS?",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(smoke_test())
