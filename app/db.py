"""DuckDB connection helper. Read-only, single shared connection."""
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


def fetchall(sql: str, params: tuple | list | dict | None = None) -> list[tuple]:
    with _lock:
        c = get_conn()
        cur = c.execute(sql, params) if params is not None else c.execute(sql)
        return cur.fetchall()


def fetchone(sql: str, params: tuple | list | dict | None = None) -> tuple | None:
    with _lock:
        c = get_conn()
        cur = c.execute(sql, params) if params is not None else c.execute(sql)
        return cur.fetchone()


def fetchcols(sql: str, params: tuple | list | dict | None = None) -> tuple[list[str], list[tuple]]:
    with _lock:
        c = get_conn()
        cur = c.execute(sql, params) if params is not None else c.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, rows
