"""SCDE dashboard queries. All read-only, all parameterized.

Conventions enforced here:
- District exclusions: lookup_district_exclusions where Exclude_Scope='all_reports' (filtered out)
- Reported_Flag = TRUE for any lea_revenues aggregation
- SCEIS State Total / Federal Total via vw_sceis_fi_payments_classified
- Headcount denominator: lea_headcounts.Total_Active_Enrollment for SY = FY (latest Report_Cycle)
- Negative currency convention is applied at render time, not here
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.db import fetchall, fetchone

# ──────────────────────────────────────────────────────────────────────
# Dropdown / metadata
# ──────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def excluded_district_ids() -> list[str]:
    rows = fetchall(
        "SELECT District_ID FROM lookup_district_exclusions WHERE Exclude_Scope = 'all_reports'"
    )
    return [r[0] for r in rows]


@lru_cache(maxsize=1)
def list_districts() -> list[dict[str, str]]:
    excl = excluded_district_ids()
    placeholders = ",".join("?" * len(excl)) if excl else "''"
    rows = fetchall(
        f"""
        SELECT District_ID, District_Name
        FROM dim_district
        WHERE District_ID NOT IN ({placeholders})
        ORDER BY District_Name
        """,
        excl or [],
    )
    return [{"id": r[0], "name": r[1]} for r in rows]


@lru_cache(maxsize=1)
def list_fiscal_years_lea() -> list[int]:
    rows = fetchall("SELECT DISTINCT FY FROM lea_revenues ORDER BY FY")
    return [r[0] for r in rows]


@lru_cache(maxsize=1)
def list_fiscal_years_sceis() -> list[int]:
    rows = fetchall(
        "SELECT DISTINCT Fiscal_Year FROM vw_sceis_fi_payments_classified WHERE Fiscal_Year IS NOT NULL ORDER BY Fiscal_Year"
    )
    return [r[0] for r in rows]


@lru_cache(maxsize=1)
def current_sceis_fy() -> int | None:
    row = fetchone("SELECT MAX(Fiscal_Year) FROM vw_sceis_fi_payments_classified")
    return row[0] if row else None


def get_district(district_id: str) -> dict | None:
    row = fetchone(
        "SELECT District_ID, District_Name FROM dim_district WHERE District_ID = ?", [district_id]
    )
    return {"id": row[0], "name": row[1]} if row else None


# ──────────────────────────────────────────────────────────────────────
# Bucketing logic
# ──────────────────────────────────────────────────────────────────────

# CASE expression: maps a (Stream_Type, Category) combo to one of six display buckets.
# Used in compare-table, multi-fy, and the chart segments.
BUCKET_CASE = """
CASE
  WHEN cdfs.Stream_Type = 'Local' AND cdfs.Category = 'Taxes & Fees'                    THEN 'Local: Taxes & Fees'
  WHEN cdfs.Stream_Type = 'Local' AND cdfs.Category = 'District Services'               THEN 'Local: District Services'
  WHEN cdfs.Stream_Type = 'Local' AND cdfs.Category = 'Investments, Donations & Other'  THEN 'Local: Investments & Donations'
  WHEN cdfs.Stream_Type = 'Local'                                                       THEN 'Local: Other'
  WHEN cdfs.Stream_Type = 'State'                                                       THEN 'State (LEA self-report)'
  WHEN cdfs.Stream_Type = 'Federal'                                                     THEN 'Federal (LEA self-report)'
  ELSE 'Uncategorized'
END
"""

LEA_BUCKETS = [
    "Local: Taxes & Fees",
    "Local: District Services",
    "Local: Investments & Donations",
    "Local: Other",
    "State (LEA self-report)",
    "Federal (LEA self-report)",
    "Uncategorized",
]

DISPLAY_BUCKETS = [
    "Local: Taxes & Fees",
    "Local: District Services",
    "Local: Investments & Donations",
    "Local: Other",
    "State (SCEIS)",
    "Federal (SCEIS)",
]


# ──────────────────────────────────────────────────────────────────────
# Per-pupil denominator — 135-day Membership ADM
# ──────────────────────────────────────────────────────────────────────
#
# Per CLAUDE.md, the per-pupil denominator across all reports is the
# 135-day Membership ADM = SUM(ADM) over the Group 1 mutually-exclusive
# base categories (BASE_K12, SPED, CTE) in `lea_wpu_category`. This is
# the same number that appears as the `MembershipTotals:` row in the
# BSC ADM source files.
#
# Barnwell rule: in FY2024+, districts 0645 and 0648 are reported as
# part of consolidated 0601. The FY25 source data already consolidates;
# the FY24 source still has them split. The helpers below sum across
# all three IDs into 0601 from FY24 onward, returning None for 0645 and
# 0648 when asked for those IDs in FY24+.

_MEMBERSHIP_BASE_CATS = ("BASE_K12", "SPED", "CTE")
_BARNWELL_CONSOLIDATION_FROM_FY = 2024
_BARNWELL_LEGACY_IDS = ("0645", "0648")
_BARNWELL_MERGED_ID = "0601"


def get_membership_adm(district_id: str, fy: int) -> int | None:
    """135-day Membership ADM for one district in one FY. Returns None
    if no rows exist (e.g., charter authorizers in FYs before they had
    category data, or legacy Barnwell IDs in FY24+)."""
    if (fy >= _BARNWELL_CONSOLIDATION_FROM_FY
            and district_id in _BARNWELL_LEGACY_IDS):
        return None
    if (fy >= _BARNWELL_CONSOLIDATION_FROM_FY
            and district_id == _BARNWELL_MERGED_ID):
        ids = (_BARNWELL_MERGED_ID,) + _BARNWELL_LEGACY_IDS
        placeholders = ",".join("?" * len(ids))
        cat_placeholders = ",".join("?" * len(_MEMBERSHIP_BASE_CATS))
        row = fetchone(
            f"""
            SELECT SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID IN ({placeholders})
              AND Fiscal_Year = ?
              AND Report_Cycle = 135
              AND Category IN ({cat_placeholders})
            """,
            [*ids, fy, *_MEMBERSHIP_BASE_CATS],
        )
    else:
        cat_placeholders = ",".join("?" * len(_MEMBERSHIP_BASE_CATS))
        row = fetchone(
            f"""
            SELECT SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID = ?
              AND Fiscal_Year = ?
              AND Report_Cycle = 135
              AND Category IN ({cat_placeholders})
            """,
            [district_id, fy, *_MEMBERSHIP_BASE_CATS],
        )
    val = row[0] if row else None
    return int(round(float(val))) if val is not None else None


def get_membership_adm_by_fy(district_id: str) -> dict[int, int]:
    """135-day Membership ADM by FY for one district. Applies Barnwell
    consolidation: when district_id='0601', sums 0601+0645+0648 for
    FY24+; pre-FY24 returns 0601's own row only. Asking for legacy
    0645 or 0648 returns only their pre-FY24 rows."""
    cat_placeholders = ",".join("?" * len(_MEMBERSHIP_BASE_CATS))

    if district_id == _BARNWELL_MERGED_ID:
        ids = (_BARNWELL_MERGED_ID,) + _BARNWELL_LEGACY_IDS
        id_placeholders = ",".join("?" * len(ids))
        # Pre-consolidation FYs: only 0601's own rows (none, in practice).
        # Post-consolidation FYs (FY24+): sum across all three IDs.
        rows = fetchall(
            f"""
            SELECT Fiscal_Year, SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID = ? AND Fiscal_Year < ?
              AND Report_Cycle = 135 AND Category IN ({cat_placeholders})
            GROUP BY Fiscal_Year
            UNION ALL
            SELECT Fiscal_Year, SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID IN ({id_placeholders}) AND Fiscal_Year >= ?
              AND Report_Cycle = 135 AND Category IN ({cat_placeholders})
            GROUP BY Fiscal_Year
            ORDER BY Fiscal_Year
            """,
            [_BARNWELL_MERGED_ID, _BARNWELL_CONSOLIDATION_FROM_FY,
             *_MEMBERSHIP_BASE_CATS,
             *ids, _BARNWELL_CONSOLIDATION_FROM_FY,
             *_MEMBERSHIP_BASE_CATS],
        )
    elif district_id in _BARNWELL_LEGACY_IDS:
        rows = fetchall(
            f"""
            SELECT Fiscal_Year, SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID = ?
              AND Fiscal_Year < ?
              AND Report_Cycle = 135
              AND Category IN ({cat_placeholders})
            GROUP BY Fiscal_Year
            ORDER BY Fiscal_Year
            """,
            [district_id, _BARNWELL_CONSOLIDATION_FROM_FY,
             *_MEMBERSHIP_BASE_CATS],
        )
    else:
        rows = fetchall(
            f"""
            SELECT Fiscal_Year, SUM(ADM)
            FROM lea_wpu_category
            WHERE District_ID = ?
              AND Report_Cycle = 135
              AND Category IN ({cat_placeholders})
            GROUP BY Fiscal_Year
            ORDER BY Fiscal_Year
            """,
            [district_id, *_MEMBERSHIP_BASE_CATS],
        )
    return {int(r[0]): int(round(float(r[1]))) for r in rows if r[1] is not None}


# ──────────────────────────────────────────────────────────────────────
# Headcount — kept for non-per-pupil uses (raw enrollment context,
# partial-FY indicators, demographic breakdowns). DO NOT use as a
# per-pupil denominator; use get_membership_adm instead.
# ──────────────────────────────────────────────────────────────────────


def get_headcount(district_id: str, fy: int) -> int | None:
    """45-day Total_Active_Enrollment for the SY matching FY. Use only
    for non-per-pupil contexts (raw enrollment, partial-FY indicator).
    For per-pupil math, use get_membership_adm."""
    row = fetchone(
        """
        SELECT Total_Active_Enrollment
        FROM lea_headcounts
        WHERE District_ID = ? AND SY = ? AND Report_Cycle = 45
        """,
        [district_id, fy],
    )
    return int(row[0]) if row and row[0] is not None else None


def get_headcounts_by_fy(district_id: str) -> dict[int, int]:
    """45-day Total_Active_Enrollment by SY for one district. Use only
    for non-per-pupil contexts."""
    rows = fetchall(
        """
        SELECT SY, Total_Active_Enrollment
        FROM lea_headcounts
        WHERE District_ID = ? AND Report_Cycle = 45
        ORDER BY SY
        """,
        [district_id],
    )
    return {int(r[0]): int(r[1]) for r in rows if r[1] is not None}


# ──────────────────────────────────────────────────────────────────────
# Map data — district revenue per pupil, FY-scoped
# ──────────────────────────────────────────────────────────────────────


def get_map_features(fy: int) -> dict[str, Any]:
    """Return a GeoJSON FeatureCollection. Each feature has revenue_per_pupil for the FY."""
    excl = excluded_district_ids()
    placeholders = ",".join("?" * len(excl)) if excl else "''"

    rows = fetchall(
        f"""
        WITH rev AS (
          SELECT District_ID, SUM(Amount) AS total_revenue
          FROM lea_revenues
          WHERE FY = ? AND Reported_Flag = TRUE AND District_ID NOT IN ({placeholders})
          GROUP BY District_ID
        ),
        hc AS (
          SELECT District_ID, Total_Active_Enrollment AS headcount
          FROM lea_headcounts
          WHERE SY = ? AND Report_Cycle = 45
        )
        SELECT
          g.District_ID,
          d.District_Name,
          g.Geometry_GeoJSON,
          g.Centroid_Lon,
          g.Centroid_Lat,
          rev.total_revenue,
          hc.headcount
        FROM dim_district_geometry g
        LEFT JOIN dim_district d USING (District_ID)
        LEFT JOIN rev USING (District_ID)
        LEFT JOIN hc  USING (District_ID)
        WHERE g.Has_Geometry = TRUE
          AND g.District_ID NOT IN ({placeholders})
        """,
        [fy, *excl, fy, *excl],
    )

    features = []
    for did, name, geom_json, lon, lat, total_rev, hc in rows:
        try:
            geom = json.loads(geom_json) if geom_json else None
        except Exception:
            geom = None
        if not geom:
            continue
        rev_pp = float(total_rev) / hc if (total_rev and hc) else None
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "District_ID": did,
                "District_Name": name,
                "total_revenue": float(total_rev) if total_rev is not None else None,
                "headcount": hc,
                "revenue_per_pupil": rev_pp,
                "centroid": [lon, lat] if lon is not None and lat is not None else None,
            },
        })

    return {"type": "FeatureCollection", "features": features}


# ──────────────────────────────────────────────────────────────────────
# Detail report — one district + FY, hierarchical leaf rows
# ──────────────────────────────────────────────────────────────────────


def get_detail_rows(district_id: str, fy: int) -> dict[str, Any]:
    """Return leaves grouped under their Rollup_Level=2 parent for an
    expand/collapse UI. Leaves whose computed parent (LEFT(code,2)||'00')
    has no Level-2 row in `code_district_funding_streams` self-parent —
    the parent row IS the leaf, marked is_orphan=True. Level-1 and
    Level-2 placeholder rows in lea_revenues (which carry $0) are
    filtered via Rollup_Level >= 3."""
    rows = fetchall(
        f"""
        WITH leaf_rows AS (
          SELECT
            lr.Revenue_Code AS code,
            cdfs.Stream_Type,
            cdfs.Display_Title AS leaf_title,
            cdfs.Rollup_Level AS leaf_level,
            cac.Full_Name,
            cac.Short_Description,
            cac.Full_Description,
            lr.Amount,
            LEFT(lr.Revenue_Code, 2) || '00' AS computed_parent,
            {BUCKET_CASE} AS bucket
          FROM lea_revenues lr
          JOIN code_district_funding_streams cdfs
                 ON lr.Revenue_Code = cdfs.REV_Code
          LEFT JOIN code_accounting_codes cac
                 ON cac.Code = lr.Revenue_Code AND cac.Type = 'Revenue'
          JOIN vw_revenue_code_status v
                 ON v.REV_Code = lr.Revenue_Code
          WHERE lr.District_ID = ?
            AND lr.FY = ?
            AND lr.Reported_Flag = TRUE
            AND v.Is_Statewide_Dormant = FALSE
            AND cdfs.Rollup_Level >= 3
        )
        SELECT
          l.Stream_Type,
          COALESCE(p.REV_Code, l.code) AS parent_code,
          COALESCE(p.Display_Title, l.leaf_title) AS parent_title,
          (p.REV_Code IS NULL) AS is_orphan,
          l.code, l.leaf_title, l.leaf_level,
          l.Full_Name, l.Short_Description, l.Full_Description,
          l.Amount, l.bucket
        FROM leaf_rows l
        LEFT JOIN code_district_funding_streams p
               ON p.REV_Code = l.computed_parent
              AND p.Rollup_Level = 2
        ORDER BY l.Stream_Type NULLS LAST, parent_code, l.code
        """,
        [district_id, fy],
    )

    items: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    by_stream: dict[str, dict[str, Any]] = {}
    parent_index: dict[tuple[str, str], dict[str, Any]] = {}

    for r in rows:
        (stream, parent_code, parent_title, is_orphan, code, leaf_title, leaf_level,
         full_name, short_desc, full_desc, amount, bucket) = r
        amount_f = float(amount) if amount is not None else 0.0
        leaf = {
            "code": code,
            "stream": stream,
            "display_title": leaf_title,
            "rollup_level": leaf_level,
            "full_name": full_name or leaf_title,
            "short_description": short_desc or "",
            "full_description": full_desc or "",
            "amount": amount_f,
            "bucket": bucket,
        }
        items.append(leaf)

        stream_key = stream or "Uncategorized"
        sg = by_stream.get(stream_key)
        if sg is None:
            sg = {"stream": stream_key, "parents": [], "stream_total": 0.0}
            by_stream[stream_key] = sg
            groups.append(sg)

        pkey = (stream_key, parent_code)
        parent = parent_index.get(pkey)
        if parent is None:
            parent = {
                "code": parent_code,
                "title": parent_title or parent_code,
                "is_orphan": bool(is_orphan),
                "amount": 0.0,
                "leaves": [],
            }
            parent_index[pkey] = parent
            sg["parents"].append(parent)
        parent["leaves"].append(leaf)
        parent["amount"] += amount_f
        sg["stream_total"] += amount_f

    # Stable stream order matching the previous renderer
    stream_order = {"Local": 0, "State": 1, "Federal": 2}
    groups.sort(key=lambda g: stream_order.get(g["stream"], 99))

    reported = bool(rows) or _has_any_lea_row(district_id, fy)

    sceis_state, sceis_federal = get_sceis_stream_totals(district_id, fy)
    headcount = get_headcount(district_id, fy)
    district = get_district(district_id) or {"id": district_id, "name": district_id}

    return {
        "district": district,
        "fy": fy,
        "headcount": headcount,
        "items": items,
        "groups": groups,
        "reported": reported,
        "sceis_state_total": sceis_state,
        "sceis_federal_total": sceis_federal,
    }


def _has_any_lea_row(district_id: str, fy: int) -> bool:
    row = fetchone(
        "SELECT 1 FROM lea_revenues WHERE District_ID = ? AND FY = ? AND Reported_Flag = TRUE LIMIT 1",
        [district_id, fy],
    )
    return row is not None


def get_sceis_stream_totals(district_id: str, fy: int) -> tuple[float | None, float | None]:
    rows = fetchall(
        """
        SELECT Funding_Stream, SUM(Amount)
        FROM vw_sceis_fi_payments_classified
        WHERE District_ID = ? AND Fiscal_Year = ?
        GROUP BY 1
        """,
        [district_id, fy],
    )
    state = federal = None
    for stream, amt in rows:
        if stream == "State":
            state = float(amt) if amt is not None else None
        elif stream == "Federal":
            federal = float(amt) if amt is not None else None
    return state, federal


# ──────────────────────────────────────────────────────────────────────
# Single-FY comparison — all districts × buckets
# ──────────────────────────────────────────────────────────────────────


def get_compare_table(fy: int) -> dict[str, Any]:
    excl = excluded_district_ids()
    placeholders = ",".join("?" * len(excl)) if excl else "''"

    # LEA-sourced sub-bucket aggregates per district
    lea_rows = fetchall(
        f"""
        SELECT
          lr.District_ID,
          {BUCKET_CASE} AS bucket,
          SUM(lr.Amount) AS amt
        FROM lea_revenues lr
        LEFT JOIN code_district_funding_streams cdfs
               ON lr.Revenue_Code = cdfs.REV_Code
        WHERE lr.FY = ?
          AND lr.Reported_Flag = TRUE
          AND lr.District_ID NOT IN ({placeholders})
        GROUP BY 1, 2
        """,
        [fy, *excl],
    )

    # SCEIS State & Federal totals per district
    sceis_rows = fetchall(
        f"""
        SELECT District_ID, Funding_Stream, SUM(Amount)
        FROM vw_sceis_fi_payments_classified
        WHERE Fiscal_Year = ?
          AND District_ID IS NOT NULL
          AND District_ID NOT IN ({placeholders})
        GROUP BY 1, 2
        """,
        [fy, *excl],
    )

    # Headcount per district for the SY (45-day per CLAUDE.md convention)
    hc_rows = fetchall(
        f"""
        SELECT District_ID, Total_Active_Enrollment
        FROM lea_headcounts
        WHERE SY = ? AND Report_Cycle = 45 AND District_ID NOT IN ({placeholders})
        """,
        [fy, *excl],
    )

    # District names
    name_rows = fetchall(
        f"""
        SELECT District_ID, District_Name
        FROM dim_district
        WHERE District_ID NOT IN ({placeholders})
        """,
        excl or [],
    )
    names = {r[0]: r[1] for r in name_rows}

    # Build per-district records
    by_district: dict[str, dict[str, Any]] = {
        did: {
            "district_id": did,
            "district_name": name,
            "buckets": {b: 0.0 for b in DISPLAY_BUCKETS},
            "lea_state_total": 0.0,
            "lea_federal_total": 0.0,
            "headcount": None,
            "reported": False,
        }
        for did, name in names.items()
    }

    for did, bucket, amt in lea_rows:
        rec = by_district.get(did)
        if not rec:
            continue
        rec["reported"] = True
        if bucket and bucket.startswith("Local:"):
            rec["buckets"][bucket] = rec["buckets"].get(bucket, 0.0) + float(amt or 0)
        elif bucket == "State (LEA self-report)":
            rec["lea_state_total"] += float(amt or 0)
        elif bucket == "Federal (LEA self-report)":
            rec["lea_federal_total"] += float(amt or 0)

    for did, stream, amt in sceis_rows:
        rec = by_district.get(did)
        if not rec:
            continue
        amt_f = float(amt or 0)
        if stream == "State":
            rec["buckets"]["State (SCEIS)"] = rec["buckets"].get("State (SCEIS)", 0.0) + amt_f
        elif stream == "Federal":
            rec["buckets"]["Federal (SCEIS)"] = rec["buckets"].get("Federal (SCEIS)", 0.0) + amt_f

    for did, hc in hc_rows:
        rec = by_district.get(did)
        if rec and hc is not None:
            rec["headcount"] = int(hc)

    rows = sorted(by_district.values(), key=lambda r: r["district_name"] or "")
    rows = [r for r in rows if r["reported"] or sum(r["buckets"].values()) > 0]

    # Compute totals + per-pupil + statewide weighted avg
    statewide = {b: 0.0 for b in DISPLAY_BUCKETS}
    statewide_hc = 0
    statewide_dollars = 0.0
    for r in rows:
        r["grand_total"] = sum(r["buckets"].values())
        if r["headcount"]:
            r["per_pupil"] = {b: v / r["headcount"] for b, v in r["buckets"].items()}
            r["per_pupil_total"] = r["grand_total"] / r["headcount"]
        else:
            r["per_pupil"] = None
            r["per_pupil_total"] = None
        for b, v in r["buckets"].items():
            statewide[b] += v
        statewide_dollars += r["grand_total"]
        if r["headcount"]:
            statewide_hc += r["headcount"]

    statewide_per_pupil = {b: (v / statewide_hc if statewide_hc else None) for b, v in statewide.items()}
    statewide_pp_total = (statewide_dollars / statewide_hc) if statewide_hc else None

    return {
        "fy": fy,
        "rows": rows,
        "buckets": DISPLAY_BUCKETS,
        "statewide": {
            "buckets": statewide,
            "per_pupil": statewide_per_pupil,
            "headcount": statewide_hc,
            "grand_total": statewide_dollars,
            "per_pupil_total": statewide_pp_total,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Multi-FY for one district
# ──────────────────────────────────────────────────────────────────────


def get_multi_fy_district(district_id: str) -> dict[str, Any]:
    fys = list_fiscal_years_lea()
    district = get_district(district_id) or {"id": district_id, "name": district_id}

    rows_per_fy: list[dict[str, Any]] = []
    for fy in fys:
        lea_rows = fetchall(
            f"""
            SELECT {BUCKET_CASE} AS bucket, SUM(lr.Amount)
            FROM lea_revenues lr
            LEFT JOIN code_district_funding_streams cdfs
                   ON lr.Revenue_Code = cdfs.REV_Code
            WHERE lr.District_ID = ?
              AND lr.FY = ?
              AND lr.Reported_Flag = TRUE
            GROUP BY 1
            """,
            [district_id, fy],
        )
        buckets = {b: 0.0 for b in DISPLAY_BUCKETS}
        reported = False
        for bucket, amt in lea_rows:
            reported = True
            if bucket and bucket.startswith("Local:"):
                buckets[bucket] += float(amt or 0)

        sceis_state, sceis_federal = get_sceis_stream_totals(district_id, fy)
        if sceis_state is not None:
            buckets["State (SCEIS)"] = sceis_state
        if sceis_federal is not None:
            buckets["Federal (SCEIS)"] = sceis_federal

        hc = get_headcount(district_id, fy)
        grand = sum(buckets.values())
        rows_per_fy.append({
            "fy": fy,
            "buckets": buckets,
            "grand_total": grand,
            "headcount": hc,
            "per_pupil": {b: (v / hc if hc else None) for b, v in buckets.items()},
            "per_pupil_total": (grand / hc) if hc else None,
            "reported": reported,
        })

    return {
        "district": district,
        "rows": rows_per_fy,
        "buckets": DISPLAY_BUCKETS,
    }


# ──────────────────────────────────────────────────────────────────────
# YTD monthly — SCEIS by posting month
# ──────────────────────────────────────────────────────────────────────


def get_ytd_monthly(district_id: str, fy: int | None = None) -> dict[str, Any]:
    if fy is None:
        fy = current_sceis_fy()
    if fy is None:
        return {"district_id": district_id, "fy": None, "rows": []}

    # SC fiscal year = July 1 of (fy-1) through June 30 of fy. Map to fiscal months 1-12 (July=1, June=12).
    rows = fetchall(
        """
        SELECT
          EXTRACT(YEAR FROM Posting_Date) AS yr,
          EXTRACT(MONTH FROM Posting_Date) AS mo,
          Funding_Stream,
          SUM(Amount) AS amt,
          COUNT(*) AS rec_count
        FROM vw_sceis_fi_payments_classified
        WHERE District_ID = ? AND Fiscal_Year = ?
        GROUP BY 1, 2, 3
        ORDER BY 1, 2
        """,
        [district_id, fy],
    )

    by_month: dict[tuple[int, int], dict[str, Any]] = {}
    for yr, mo, stream, amt, n in rows:
        key = (int(yr), int(mo))
        rec = by_month.setdefault(key, {"year": int(yr), "month": int(mo), "streams": {}, "total": 0.0, "count": 0})
        rec["streams"][stream or "Other"] = float(amt or 0)
        rec["total"] += float(amt or 0)
        rec["count"] += int(n or 0)

    sorted_months = [by_month[k] for k in sorted(by_month.keys())]

    district = get_district(district_id) or {"id": district_id, "name": district_id}
    return {
        "district": district,
        "fy": fy,
        "rows": sorted_months,
        "data_through": fetchone(
            "SELECT MAX(Posting_Date) FROM vw_sceis_fi_payments_classified WHERE District_ID = ? AND Fiscal_Year = ?",
            [district_id, fy],
        )[0],
    }
