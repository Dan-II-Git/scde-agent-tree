#!/usr/bin/env python3
"""
Apply column descriptions from schema.json to the canonical DuckDB.

Run after db/init.sql to attach hover-friendly column comments. Any
schema-explorer or report agent can then retrieve them via standard
SQL — no custom parser needed:

    SELECT column_name, comment
    FROM duckdb_columns()
    WHERE table_name = 'sceis_detail_transaction';

Or:
    DESCRIBE TABLE sceis_detail_transaction;

Idempotent — safe to re-run after schema.json edits.
"""
import json
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.stderr.write("duckdb python module not installed.\n  pip install duckdb\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_JSON = ROOT / "db" / "schema.json"
DB_PATH = ROOT / "db" / "scde.duckdb"


def escape_sql(s: str) -> str:
    return s.replace("'", "''")


def main():
    if not SCHEMA_JSON.exists():
        sys.exit(f"Missing {SCHEMA_JSON}")
    if not DB_PATH.exists():
        sys.exit(f"Missing {DB_PATH} — run db/init.sql first.")

    schema = json.loads(SCHEMA_JSON.read_text())
    con = duckdb.connect(str(DB_PATH))

    # Get tables that actually exist in the DB so we don't fail on
    # tables that are documented but not yet created.
    existing = {row[0] for row in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name='main'"
    ).fetchall()}

    applied = 0
    skipped_tables = []
    skipped_columns = []

    for table_name, table_meta in schema["tables"].items():
        if table_name not in existing:
            skipped_tables.append(table_name)
            continue

        # Apply table-level comment using purpose
        purpose = table_meta.get("purpose", "").strip()
        if purpose:
            con.execute(
                f"COMMENT ON TABLE {table_name} IS '{escape_sql(purpose)}'"
            )
            applied += 1

        # Get columns that actually exist on this table
        existing_cols = {row[0] for row in con.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE table_name = ? AND schema_name='main'",
            [table_name],
        ).fetchall()}

        for col_name, description in table_meta.get("columns", {}).items():
            if col_name not in existing_cols:
                skipped_columns.append(f"{table_name}.{col_name}")
                continue
            con.execute(
                f"COMMENT ON COLUMN {table_name}.{col_name} "
                f"IS '{escape_sql(description)}'"
            )
            applied += 1

    con.close()

    print(f"OK: Applied {applied} comments from schema.json")
    if skipped_tables:
        print(f"  Skipped {len(skipped_tables)} table(s) not yet in DB: "
              f"{', '.join(skipped_tables)}")
    if skipped_columns:
        print(f"  Skipped {len(skipped_columns)} column(s) not in DB: "
              f"{', '.join(skipped_columns[:5])}"
              f"{'...' if len(skipped_columns) > 5 else ''}")


if __name__ == "__main__":
    main()
