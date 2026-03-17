"""Discovered sources database interface."""

import logging

from agentiq_labclaw.db.connection import get_connection

logger = logging.getLogger("labclaw.db.discovered_sources")


def register_source(url: str, domain: str, discovered_by: str = "grok", notes: str | None = None) -> int:
    """Register a newly discovered data source. Returns the source ID."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO discovered_sources (url, domain, discovered_by, notes) VALUES (%s, %s, %s, %s) RETURNING id",
            (url, domain, discovered_by, notes),
        )
        source_id = cur.fetchone()[0]
    logger.info("Registered source %d: %s (%s)", source_id, url, domain)
    return source_id


def validate_source(source_id: int):
    """Mark a discovered source as validated."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE discovered_sources SET validated = TRUE WHERE id = %s", (source_id,))
    logger.info("Validated source %d", source_id)


def list_unvalidated() -> list[dict]:
    """List all unvalidated discovered sources."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id, url, domain, discovered_by, discovered_at, notes FROM discovered_sources WHERE validated = FALSE")
        rows = cur.fetchall()
        return [
            {"id": r[0], "url": r[1], "domain": r[2], "discovered_by": r[3], "discovered_at": r[4].isoformat() if r[4] else None, "notes": r[5]}
            for r in rows
        ]
