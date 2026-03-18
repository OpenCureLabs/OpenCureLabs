"""PostgreSQL connection management."""

import logging
import os

import psycopg2

logger = logging.getLogger("labclaw.db")

_connection = None


def get_connection():
    """Get or create a PostgreSQL connection to the opencurelabs database."""
    global _connection
    if _connection is None or _connection.closed:
        db_url = os.environ.get("POSTGRES_URL", "postgresql://localhost:5433/opencurelabs")
        logger.info("Connecting to PostgreSQL: %s", db_url.split("@")[-1] if "@" in db_url else db_url)
        _connection = psycopg2.connect(db_url)
        _connection.autocommit = True
    return _connection


def close_connection():
    """Close the PostgreSQL connection."""
    global _connection
    if _connection and not _connection.closed:
        _connection.close()
        _connection = None
