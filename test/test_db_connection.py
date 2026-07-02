# test_db_connection.py
"""Verify PostgreSQL connectivity using credentials from docker-compose.yml."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from app.config import config


def main() -> int:
    if not config.DB_PASSWORD:
        print("FAIL: DB_PASSWORD not resolved (check docker-compose.yml)")
        return 1

    try:
        conn = psycopg2.connect(
            host=config.DB_HOST,
            port=int(config.DB_PORT),
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        print("OK connection succeeded")
        print(cursor.fetchone())
        conn.close()
        return 0
    except Exception as exc:
        print(f"FAIL connection failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
