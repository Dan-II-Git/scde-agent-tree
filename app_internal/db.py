"""DuckDB connection helper for app_internal — read-only, shared connection.

Mirrors app/db.py so the two apps don't fight over the write-lock. Both
hold read-only connections to the same db/scde.duckdb file.
"""
from __future__ import annotations

import threading
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "scde.duckdb"

_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = duckdb.connect(str(DB_PATH), read_only=True)
            _conn.execute("SET enable_progress_bar=false")
        return _conn


def fetchall(sql: str, params=None) -> list[tuple]:
    with _lock:
        c = get_conn()
        cur = c.execute(sql, params) if params is not None else c.execute(sql)
        return cur.fetchall()


def fetchone(sql: str, params=None) -> tuple | None:
    with _lock:
        c = get_conn()
        cur = c.execute(sql, params) if params is not None else c.execute(sql)
        return cur.fetchone()
