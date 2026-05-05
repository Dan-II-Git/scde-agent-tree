"""
apply_lookup_gl_account.py
---------------------------
Loads the staged lookup_gl_account parquet into the canonical DuckDB.

Per CLAUDE.md workflow:
  code-catalog stages -> data-quality validates -> THIS script applies.

Idempotent:
  - Adds the 5 newer columns (Bridge_Type, Source, Confidence, Notes,
    Source_Row_Count) to the live table if missing.
  - DELETEs all rows then re-inserts from the parquet (full reload).
  - Re-running produces identical state.

Usage:
    python scripts/apply_lookup_gl_account.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "scde.duckdb"
PARQUET_PATH = REPO_ROOT / "data" / "staging" / "lookup_gl_account_draft.parquet"

NEW_COLUMNS = [
    ("Bridge_Type", "VARCHAR"),
    ("Source", "VARCHAR"),
    ("Confidence", "VARCHAR"),
    ("Notes", "VARCHAR"),
    ("Source_Row_Count", "INTEGER"),
]


def main() -> None:
    if not PARQUET_PATH.exists():
        raise SystemExit(f"Staging parquet missing: {PARQUET_PATH}")

    con = duckdb.connect(str(DB_PATH))

    existing = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='lookup_gl_account'"
    ).fetchall()}

    for col, sqltype in NEW_COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE lookup_gl_account ADD COLUMN {col} {sqltype}")
            print(f"  + ALTER TABLE lookup_gl_account ADD COLUMN {col} {sqltype}")

    before = con.execute("SELECT COUNT(*) FROM lookup_gl_account").fetchone()[0]
    con.execute("DELETE FROM lookup_gl_account")
    con.execute(f"""
        INSERT INTO lookup_gl_account
            (GL_Account, SAP_Category, Handbook_Code, Handbook_Type, Handbook_Name,
             Bridge_Type, Source, Confidence, Notes, Source_Row_Count)
        SELECT GL_Account, SAP_Category, Handbook_Code, Handbook_Type, Handbook_Name,
               Bridge_Type, Source, Confidence, Notes, Source_Row_Count
        FROM read_parquet(?)
    """, [str(PARQUET_PATH)])
    after = con.execute("SELECT COUNT(*) FROM lookup_gl_account").fetchone()[0]
    print(f"  rows: {before} -> {after}")

    by_bridge = con.execute(
        "SELECT Bridge_Type, COUNT(*) FROM lookup_gl_account GROUP BY 1 ORDER BY 1"
    ).fetchall()
    print("  Bridge_Type breakdown:")
    for bt, n in by_bridge:
        print(f"    {bt!s:20s} {n:>5d}")

    con.close()
    print("Apply complete.")


if __name__ == "__main__":
    main()
