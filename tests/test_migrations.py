"""
Tests for db/schema.sql and db/migrations/*.sql.

Creates a throwaway database, applies the base schema and every migration in
order, and verifies that expected columns and indexes exist. Also re-runs
each migration a second time to confirm idempotency (ADD COLUMN IF NOT EXISTS /
CREATE INDEX IF NOT EXISTS).

Runs against the local PostgreSQL instance on port 5433.
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw")
)

try:
    import psycopg2

    _admin = psycopg2.connect("postgresql://localhost:5433/postgres")
    _admin.autocommit = True
    _admin.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL not available")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_conn():
    conn = psycopg2.connect("postgresql://localhost:5433/postgres")
    conn.autocommit = True
    return conn


def _run_sql(conn, sql: str) -> None:
    cur = conn.cursor()
    cur.execute(sql)
    cur.close()


def _columns(conn, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    cols = {r[0] for r in cur.fetchall()}
    cur.close()
    return cols


def _indexes(conn, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = %s",
        (table,),
    )
    idxs = {r[0] for r in cur.fetchall()}
    cur.close()
    return idxs


# ---------------------------------------------------------------------------
# Fixture: fresh throwaway DB per test class
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def fresh_db():
    """Create a throwaway database, apply schema + migrations, yield its URL."""
    dbname = f"audit_test_migrations_{int(time.time() * 1000)}"
    admin = _admin_conn()
    try:
        _run_sql(admin, f'CREATE DATABASE "{dbname}"')
    finally:
        admin.close()

    url = f"postgresql://localhost:5433/{dbname}"
    try:
        yield dbname, url
    finally:
        # Teardown: terminate connections then drop
        admin = _admin_conn()
        try:
            _run_sql(
                admin,
                # dbname is built from time.time() — no user input, safe to inline
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid()",  # noqa: S608
            )
            _run_sql(admin, f'DROP DATABASE IF EXISTS "{dbname}"')
        finally:
            admin.close()


# ---------------------------------------------------------------------------
# Schema + migrations
# ---------------------------------------------------------------------------


class TestSchemaAndMigrations:
    def _apply_all(self, url: str) -> None:
        """Apply schema.sql and every migration in numeric order."""
        # schema.sql contains psql meta-commands (\c opencurelabs) and a
        # CREATE DATABASE line that are irrelevant inside our throwaway DB.
        raw = SCHEMA_PATH.read_text()
        schema_sql = "\n".join(
            line
            for line in raw.splitlines()
            if not line.lstrip().startswith("\\")
            and not line.lstrip().upper().startswith("CREATE DATABASE")
        )
        conn = psycopg2.connect(url)
        conn.autocommit = True
        try:
            _run_sql(conn, schema_sql)
            for mig in sorted(MIGRATIONS_DIR.glob("*.sql")):
                _run_sql(conn, mig.read_text())
        finally:
            conn.close()

    def test_schema_applies(self, fresh_db):
        _dbname, url = fresh_db
        self._apply_all(url)
        conn = psycopg2.connect(url)
        try:
            # Spot-check a handful of core tables created by schema.sql
            cur = conn.cursor()
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = {r[0] for r in cur.fetchall()}
            cur.close()
            for t in (
                "agent_runs",
                "pipeline_runs",
                "experiment_results",
                "critique_log",
                "discovered_sources",
                "vast_spend",
            ):
                assert t in tables, f"missing table: {t}"
        finally:
            conn.close()

    def test_migration_002_adds_species(self, fresh_db):
        _dbname, url = fresh_db
        conn = psycopg2.connect(url)
        try:
            cols = _columns(conn, "experiment_results")
            assert "species" in cols
            idxs = _indexes(conn, "experiment_results")
            assert "idx_experiment_results_species" in idxs
        finally:
            conn.close()

    def test_migration_003_adds_synthetic(self, fresh_db):
        _dbname, url = fresh_db
        conn = psycopg2.connect(url)
        try:
            cols = _columns(conn, "experiment_results")
            assert "synthetic" in cols
            idxs = _indexes(conn, "experiment_results")
            assert "idx_experiment_results_synthetic" in idxs
        finally:
            conn.close()

    def test_migration_004_adds_genesis_run_id(self, fresh_db):
        _dbname, url = fresh_db
        conn = psycopg2.connect(url)
        try:
            for table, idx in (
                ("batch_jobs", "idx_batch_jobs_genesis_run_id"),
                ("vast_spend", "idx_vast_spend_genesis_run_id"),
                ("llm_spend", "idx_llm_spend_genesis_run_id"),
            ):
                cols = _columns(conn, table)
                assert "genesis_run_id" in cols, f"{table}.genesis_run_id missing"
                idxs = _indexes(conn, table)
                assert idx in idxs, f"{idx} missing on {table}"
        finally:
            conn.close()

    def test_migrations_are_idempotent(self, fresh_db):
        """Re-applying every migration a second time must not error."""
        _dbname, url = fresh_db
        conn = psycopg2.connect(url)
        conn.autocommit = True
        try:
            for mig in sorted(MIGRATIONS_DIR.glob("*.sql")):
                _run_sql(conn, mig.read_text())
        finally:
            conn.close()
