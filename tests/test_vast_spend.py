"""
Tests for the vast_spend DB layer — _ensure_spend_table, _record_spend_start,
_record_spend_end, and get_total_spend (GENESIS_START filtering).

Runs against the local PostgreSQL instance on port 5433.
Each test cleans up after itself via the autouse fixture.
"""

import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw")
)

try:
    import psycopg2  # noqa: F401
    from agentiq_labclaw.compute import vast_dispatcher as vd

    _conn = vd._get_db_connection()
    DB_AVAILABLE = _conn is not None
    if _conn is not None:
        _conn.close()
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_vast_spend():
    """Delete rows produced by these tests."""
    yield
    conn = vd._get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM vast_spend WHERE skill_name LIKE 'test_%%'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _reset_genesis_env(monkeypatch):
    """Ensure GENESIS_START doesn't leak between tests."""
    monkeypatch.delenv("GENESIS_START", raising=False)
    yield


def _fetch(spend_id, conn=None):
    """Helper — fetch a vast_spend row as a dict."""
    own = conn is None
    if own:
        conn = vd._get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, instance_id, skill_name, gpu_name, cost_per_hour, "
            "started_at, ended_at, total_cost, genesis_run_id "
            "FROM vast_spend WHERE id = %s",
            (spend_id,),
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "instance_id": row[1],
            "skill_name": row[2],
            "gpu_name": row[3],
            "cost_per_hour": row[4],
            "started_at": row[5],
            "ended_at": row[6],
            "total_cost": row[7],
            "genesis_run_id": row[8],
        }
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# _ensure_spend_table
# ---------------------------------------------------------------------------


class TestEnsureSpendTable:
    def test_is_idempotent(self):
        conn = vd._get_db_connection()
        assert conn is not None
        try:
            # Call twice — must not raise
            vd._ensure_spend_table(conn)
            vd._ensure_spend_table(conn)
            cur = conn.cursor()
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'vast_spend'"
            )
            cols = {r[0] for r in cur.fetchall()}
            cur.close()
        finally:
            conn.close()
        # Core columns required by the spend-tracking code
        for c in (
            "id",
            "instance_id",
            "skill_name",
            "gpu_name",
            "cost_per_hour",
            "started_at",
            "ended_at",
            "total_cost",
        ):
            assert c in cols, f"missing column: {c}"


# ---------------------------------------------------------------------------
# _record_spend_start / _record_spend_end
# ---------------------------------------------------------------------------


class TestRecordSpend:
    def test_start_returns_id_and_inserts_row(self):
        spend_id = vd._record_spend_start(
            skill_name="test_protein_fold",
            instance_id=12345,
            gpu_name="RTX_5090",
            cost_per_hour=0.42,
        )
        assert isinstance(spend_id, int)
        assert spend_id > 0

        row = _fetch(spend_id)
        assert row is not None
        assert row["instance_id"] == 12345
        assert row["skill_name"] == "test_protein_fold"
        assert row["gpu_name"] == "RTX_5090"
        assert abs(row["cost_per_hour"] - 0.42) < 1e-6
        assert row["started_at"] is not None
        assert row["ended_at"] is None
        assert row["genesis_run_id"] is None

    def test_end_updates_total_cost_and_ended_at(self):
        spend_id = vd._record_spend_start(
            "test_docking", 999, "RTX_4090", 0.30
        )
        assert spend_id is not None

        vd._record_spend_end(spend_id, total_cost=1.25)

        row = _fetch(spend_id)
        assert row is not None
        assert row["ended_at"] is not None
        assert abs(row["total_cost"] - 1.25) < 1e-6

    def test_end_with_none_spend_id_is_noop(self):
        # Must not raise, must not touch DB
        vd._record_spend_end(None, total_cost=99.9)

    def test_start_populates_genesis_run_id_from_env(self, monkeypatch):
        import datetime

        ts = datetime.datetime(2026, 3, 20, 21, 9, 47).timestamp()
        monkeypatch.setenv("GENESIS_START", str(ts))

        spend_id = vd._record_spend_start(
            "test_genesis_tagged", 111, "RTX_5070", 0.20
        )
        assert spend_id is not None
        row = _fetch(spend_id)
        assert row["genesis_run_id"] == "genesis-20260320-210947"


# ---------------------------------------------------------------------------
# get_total_spend
# ---------------------------------------------------------------------------


class TestGetTotalSpend:
    def test_sums_with_genesis_start_filter(self, monkeypatch):
        import datetime
        import time

        # Insert an "old" row (before GENESIS_START)
        old_id = vd._record_spend_start("test_old_run", 1, "RTX_5090", 0.10)
        vd._record_spend_end(old_id, total_cost=10.0)

        # Backdate the old row manually so it falls before GENESIS_START
        conn = vd._get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE vast_spend SET started_at = %s WHERE id = %s",
            (datetime.datetime(2020, 1, 1), old_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        # Set GENESIS_START to now, then record a new row
        monkeypatch.setenv("GENESIS_START", str(time.time()))
        new_id = vd._record_spend_start("test_new_run", 2, "RTX_5090", 0.10)
        vd._record_spend_end(new_id, total_cost=3.5)

        total = vd.get_total_spend()
        # Should count only the new row — but other test_* rows from this DB may
        # also fall within the window, so assert it includes our new value at least.
        assert total >= 3.5
        # And excludes the old row (would be 13.5 if not filtered)
        assert total < 10.0 + 3.5  # i.e. not 13.5
