"""
load_dim_functional_area.py
---------------------------
Loads db/dim_functional_area.json into the canonical DuckDB table
dim_functional_area.

The JSON was staged by code-catalog and validated by data-quality
(YELLOW verdict 2026-05-14, corrections applied: H630_SRAE reclassified
to Federal; 6 Z-rollup codes downgraded to medium confidence).

IDEMPOTENCY: DROP-then-CREATE-then-INSERT (the table has no downstream
FK dependents — it is joined by dimension lookup, not as a PK target).

Usage:
    python scripts/load_dim_functional_area.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = REPO_ROOT / "db" / "scde.duckdb"
JSON_PATH = REPO_ROOT / "db" / "dim_functional_area.json"


def load(dry_run: bool = False) -> None:
    with open(JSON_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    mapping: dict = doc["mapping"]

    rows: list[tuple] = []
    for code, entry in mapping.items():
        rows.append((
            code,
            entry.get("name"),          # may be None
            entry["category"],
            entry["confidence"],
            entry.get("fy26_5xxx_spend"),  # may be None / 0.0
            entry.get("note"),          # may be None
        ))

    print(f"Prepared {len(rows)} rows from {JSON_PATH.name}")

    if dry_run:
        print("DRY RUN — no DB changes made.")
        for r in rows[:5]:
            print(" ", r)
        return

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("BEGIN")

        # Snapshot existing table before replacing it (if it exists)
        existing = con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'dim_functional_area'"
        ).fetchone()[0]

        if existing:
            from datetime import datetime
            snap_name = f"dim_functional_area_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            snap_path = REPO_ROOT / "db" / "snapshots" / f"{snap_name}.parquet"
            snap_path.parent.mkdir(exist_ok=True)
            con.execute(
                f"COPY dim_functional_area TO '{snap_path}' (FORMAT PARQUET)"
            )
            print(f"Snapshot written: {snap_path}")
            con.execute("DROP TABLE dim_functional_area")

        con.execute("""
            CREATE TABLE dim_functional_area (
                Functional_Area  VARCHAR PRIMARY KEY,
                Name             VARCHAR,
                Category         VARCHAR NOT NULL,
                Confidence       VARCHAR NOT NULL,
                FY26_5xxx_Spend  DOUBLE,
                Note             VARCHAR
            )
        """)

        con.executemany(
            "INSERT INTO dim_functional_area VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

        count = con.execute("SELECT COUNT(*) FROM dim_functional_area").fetchone()[0]
        print(f"Inserted {count} rows into dim_functional_area.")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load(dry_run=args.dry_run)
