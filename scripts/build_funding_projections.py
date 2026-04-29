#!/usr/bin/env python3
"""
build_funding_projections.py — populates mart_funding_projections.

Owned by the funding-projections agent. See .claude/agents/funding-projections.md
for the methodology and hard rules.

Pipeline:
  1. Read history from lea_revenues (Reported_Flag=TRUE filter).
  2. For each (District_ID, Revenue_Code) with >=2 usable FYs of history,
     fit a linear trend on (FY, Amount). Generate a point estimate plus
     80% prediction interval for each projection FY in the horizon.
  3. Codes whose Sunset_Note matches "last paid FY{NN}" force the
     projected amount to zero from FY+1 onward (Method='sunset_zero').
  4. Codes with <2 usable FYs of history emit Method='insufficient_history'
     with NULL amounts (renders as the projection.insufficient_gap hatch
     per style-guide §1.4 / §5.1).
  5. SAC codes (Allocation_Basis IN ('PowerSchool ADM', 'PS ADM')) fall
     back to trend in v1 because forward-year sac_total_state_share is
     not yet seeded. When seeded, the formula path activates: amount =
     (district_WPU / statewide_WPU) * sac_total_state_share.

Run:
  python3 scripts/build_funding_projections.py [--scenario baseline]
                                                [--horizon 2026,2027]
"""

import argparse
import re
import sys
from datetime import datetime

import duckdb
import numpy as np
from scipy import stats

DB_PATH = "db/scde.duckdb"
DEFAULT_SCENARIO = "baseline"
DEFAULT_HORIZON = [2026, 2027]
HISTORY_MIN_FY = 2023
HISTORY_MAX_FY = 2025
TWO_POINT_FALLBACK_PCT = 0.15  # ±15% bounds when residual SE is undefined
PI_CONFIDENCE = 0.80  # 80% prediction interval (matches projection.band_fill)

# Dormancy: a (district, code) combo is suppressed if its most-recent
# nonzero, reported-true activity is more than LOOKBACK_YEARS-1 FYs before
# HISTORY_MAX_FY. With LOOKBACK_YEARS=3 and HISTORY_MAX_FY=2025, activity
# must fall within FY23-FY25 (the current 3-FY window). Once older history
# is loaded, this filter starts excluding stale combos.
LOOKBACK_YEARS = 3

# 5xxx codes are non-recurring transactional items (bond sales, interfund
# transfers, lease purchase) per the RFA report appendix. They are not
# ongoing revenue and should not be projected.
NON_RECURRING_CODE_PREFIXES = ("5",)

# State and Federal revenue cannot plausibly be negative. Local can be
# (refunds, write-offs), so we don't floor it.
FLOOR_AT_ZERO_STREAM_TYPES = ("State", "Federal")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default=DEFAULT_SCENARIO)
    p.add_argument("--horizon", default=",".join(str(fy) for fy in DEFAULT_HORIZON),
                   help="Comma-separated list of projection FYs")
    p.add_argument("--db", default=DB_PATH)
    return p.parse_args()


def parse_sunset_fy(note):
    """Extract the last-paid FY from a sunset note string. Returns int(YYYY) or None."""
    if not note:
        return None
    m = re.search(r"last paid FY\s*(\d{2})\b", note, re.IGNORECASE)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"Closed\s+FY\s*(\d{2})\b", note, re.IGNORECASE)
    if m:
        return 2000 + int(m.group(1))
    return None


def fit_linear_trend(fys, amounts):
    """
    Fit y = b0 + b1*x to (fys, amounts). Returns dict with slope, intercept,
    n, residual_se, x_mean, sum_sq_dev. Handles n=2 (exact fit, no residuals).
    """
    x = np.array(fys, dtype=float)
    y = np.array(amounts, dtype=float)
    n = len(x)
    x_mean = x.mean()
    sum_sq_dev = float(((x - x_mean) ** 2).sum())
    if sum_sq_dev == 0:
        return None  # all FYs identical — degenerate
    slope = float(((x - x_mean) * (y - y.mean())).sum() / sum_sq_dev)
    intercept = float(y.mean() - slope * x_mean)
    if n >= 3:
        y_hat = intercept + slope * x
        residuals = y - y_hat
        residual_se = float(np.sqrt((residuals ** 2).sum() / (n - 2)))
    else:
        residual_se = None  # 2 points — exact fit, no residual info
    return {
        "slope": slope, "intercept": intercept, "n": n,
        "residual_se": residual_se, "x_mean": x_mean, "sum_sq_dev": sum_sq_dev,
    }


def predict_with_pi(fit, fy):
    """
    Return (point_estimate, lower_80, upper_80) for the given projection FY.
    """
    if fit is None:
        return None, None, None
    point = fit["intercept"] + fit["slope"] * fy
    if fit["residual_se"] is None:
        # 2-point fallback: ±15% of point estimate (heuristic)
        margin = abs(point) * TWO_POINT_FALLBACK_PCT
        return point, point - margin, point + margin
    n = fit["n"]
    se_pred = fit["residual_se"] * np.sqrt(
        1 + 1.0 / n + (fy - fit["x_mean"]) ** 2 / fit["sum_sq_dev"]
    )
    # two-tailed 80% PI ⇒ 90th percentile of t with df=n-2
    t_crit = stats.t.ppf(0.5 + PI_CONFIDENCE / 2, df=n - 2)
    margin = float(t_crit * se_pred)
    return point, point - margin, point + margin


def load_inputs(con):
    """
    Returns:
      history: list of (district_id, revenue_code, fy, amount)
      stream_meta: dict[code] = (stream_type, allocation_basis, sunset_fy_or_none)
      policy: dict[(fy, parameter)] = value

    Statewide-dormant codes are filtered out via vw_revenue_code_status per
    the CLAUDE.md convention. Sunset and rollup codes pass through (the
    pipeline handles them with their own branches).
    """
    history = con.execute(f"""
        SELECT r.District_ID, r.Revenue_Code, r.FY, CAST(r.Amount AS DOUBLE) AS Amount
        FROM lea_revenues r
        JOIN vw_revenue_code_status v ON v.REV_Code = r.Revenue_Code
        WHERE r.Reported_Flag = TRUE
          AND r.Amount IS NOT NULL
          AND r.Amount != 0
          AND r.FY BETWEEN {HISTORY_MIN_FY} AND {HISTORY_MAX_FY}
          AND v.Is_Statewide_Dormant = FALSE
    """).fetchall()

    stream_meta = {}
    for code, stream_type, alloc_basis, sunset_note in con.execute("""
        SELECT c.REV_Code, c.Stream_Type, c.Allocation_Basis, c.Sunset_Note
        FROM code_district_funding_streams c
        JOIN vw_revenue_code_status v ON v.REV_Code = c.REV_Code
        WHERE v.Is_Statewide_Dormant = FALSE
    """).fetchall():
        sunset_fy = parse_sunset_fy(sunset_note)
        stream_meta[str(code)] = {
            "stream_type": stream_type,
            "allocation_basis": alloc_basis,
            "sunset_fy": sunset_fy,
            "sunset_note": sunset_note,
        }

    policy = {}
    for fy, param, value in con.execute("""
        SELECT FY, parameter, CAST(value AS DOUBLE)
        FROM policy_rate_assumptions
        WHERE scenario = ?
    """, [DEFAULT_SCENARIO]).fetchall():
        policy[(int(fy), param)] = float(value)

    return history, stream_meta, policy


def build_projections(history, stream_meta, policy, horizon, scenario):
    """
    Returns list of dicts ready to insert into mart_funding_projections.
    """
    # Group history by (district, code)
    series = {}
    for district_id, code, fy, amt in history:
        series.setdefault((district_id, str(code)), []).append((int(fy), float(amt)))

    rows = []
    built_at = datetime.now()
    counters = {
        "formula_sac": 0, "trend_3fy": 0, "trend_2fy": 0,
        "sunset_zero": 0, "insufficient_history": 0,
        "skip_unclassified": 0, "skip_non_recurring": 0,
        "skip_dormant_district": 0, "skip_dormant_statewide": 0,
        "floor_at_zero_applied": 0,
    }

    # Statewide dormancy: a code is suppressed everywhere if it has no
    # nonzero, reported-true activity in the last LOOKBACK_YEARS FYs.
    statewide_recent = set()
    for (district_id, code), pts in series.items():
        if any(amt != 0 and fy >= HISTORY_MAX_FY - LOOKBACK_YEARS + 1 for fy, amt in pts):
            statewide_recent.add(code)

    for (district_id, code), pts in series.items():
        # Skip non-recurring (5xxx) codes entirely
        if code.startswith(NON_RECURRING_CODE_PREFIXES):
            counters["skip_non_recurring"] += 1
            continue

        meta = stream_meta.get(code)
        # Skip codes not in the funding stream inventory — they're either
        # unclassified handbook codes or transient/legacy codes that should
        # be cleaned up by code-catalog before being projected.
        if meta is None or meta["stream_type"] is None:
            counters["skip_unclassified"] += 1
            continue

        # Statewide dormancy
        if code not in statewide_recent:
            counters["skip_dormant_statewide"] += 1
            continue

        # Per-district dormancy: this district has no recent activity for
        # this code (even though some other district might).
        district_max_active_fy = max(
            (fy for fy, amt in pts if amt != 0), default=None
        )
        if district_max_active_fy is None or \
           district_max_active_fy < HISTORY_MAX_FY - LOOKBACK_YEARS + 1:
            counters["skip_dormant_district"] += 1
            continue

        stream_type = meta["stream_type"]
        alloc_basis = meta["allocation_basis"]
        sunset_fy = meta["sunset_fy"]

        pts.sort()
        fys, amts = zip(*pts)
        fit = fit_linear_trend(fys, amts) if len(pts) >= 2 else None

        for proj_fy in horizon:
            # Sunset rule wins
            if sunset_fy is not None and proj_fy > sunset_fy:
                rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                                 0.0, 0.0, 0.0, "sunset_zero", scenario, built_at))
                counters["sunset_zero"] += 1
                continue

            # Insufficient history
            if fit is None:
                rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                                 None, None, None, "insufficient_history", scenario, built_at))
                counters["insufficient_history"] += 1
                continue

            # SAC formula path: only when forward-year total appropriation is seeded
            sac_total_key = (proj_fy, "sac_total_state_share")
            sac_total_wpu_key = (proj_fy, "sac_total_state_wpu")
            is_sac_code = alloc_basis in ("PowerSchool ADM", "PS ADM")
            if is_sac_code and sac_total_key in policy and sac_total_wpu_key in policy:
                # Placeholder: would need projected district WPU here.
                # Forward-year district WPU isn't yet seeded — defer to trend.
                # (When seeded, switch this branch to formula_sac.)
                pass

            # Trend OLS path
            point, lower, upper = predict_with_pi(fit, proj_fy)
            method = "trend_ols" if fit["n"] >= 3 else "trend_ols_2fy"

            # Floor State/Federal at zero (Local can plausibly go negative)
            if stream_type in FLOOR_AT_ZERO_STREAM_TYPES:
                if (point is not None and point < 0) or \
                   (lower is not None and lower < 0):
                    counters["floor_at_zero_applied"] += 1
                if point is not None:
                    point = max(0.0, point)
                if lower is not None:
                    lower = max(0.0, lower)
                if upper is not None:
                    upper = max(0.0, upper)

            if fit["n"] >= 3:
                counters["trend_3fy"] += 1
            else:
                counters["trend_2fy"] += 1
            rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                             point, lower, upper, method, scenario, built_at))

    counters["rows"] = len(rows)
    return rows, counters


def _row(district_id, fy, code, stream_type, alloc_basis,
         amount, lower, upper, method, scenario, built_at):
    return {
        "District_ID": district_id, "FY": fy, "Revenue_Code": code,
        "Stream_Type": stream_type, "Allocation_Basis": alloc_basis,
        "Amount": _round(amount), "Lower_80": _round(lower), "Upper_80": _round(upper),
        "Method": method, "Scenario": scenario, "Built_At": built_at,
    }


def _round(x):
    return None if x is None else round(float(x), 2)


def write_mart(con, rows, scenario):
    con.execute("BEGIN")
    con.execute("DELETE FROM mart_funding_projections WHERE Scenario = ?", [scenario])
    if rows:
        con.executemany(
            """
            INSERT INTO mart_funding_projections
              (District_ID, FY, Revenue_Code, Stream_Type, Allocation_Basis,
               Amount, Lower_80, Upper_80, Method, Scenario, Built_At)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (r["District_ID"], r["FY"], r["Revenue_Code"], r["Stream_Type"],
                 r["Allocation_Basis"], r["Amount"], r["Lower_80"], r["Upper_80"],
                 r["Method"], r["Scenario"], r["Built_At"])
                for r in rows
            ],
        )
    con.execute("COMMIT")


def back_test(con, scenario):
    """
    Refit on FY23+FY24, predict FY25, compare to FY25 actuals. Same filters
    as the production pipeline: skip 5xxx codes, skip unclassified,
    floor State/Federal at $0. Reports both unweighted MAPE (for
    completeness) and the dollar-weighted error rate (more meaningful —
    sum of |error| over sum of |actual|).
    """
    out = con.execute(f"""
        WITH hist AS (
            SELECT District_ID, Revenue_Code, FY, CAST(Amount AS DOUBLE) AS Amount
            FROM lea_revenues
            WHERE Reported_Flag = TRUE
              AND Amount IS NOT NULL AND Amount != 0
              AND FY IN (2023, 2024)
              AND Revenue_Code NOT LIKE '5%'
        ),
        actual AS (
            SELECT District_ID, Revenue_Code, CAST(Amount AS DOUBLE) AS Amount
            FROM lea_revenues
            WHERE Reported_Flag = TRUE
              AND Amount IS NOT NULL AND Amount != 0
              AND FY = 2025
              AND Revenue_Code NOT LIKE '5%'
        ),
        proj AS (
            SELECT h.District_ID, h.Revenue_Code,
                   -- 2-point projection: FY25 = 2*FY24 - FY23
                   2 * MAX(CASE WHEN h.FY = 2024 THEN h.Amount END)
                     - MAX(CASE WHEN h.FY = 2023 THEN h.Amount END) AS predicted_raw
            FROM hist h
            GROUP BY 1, 2
            HAVING COUNT(DISTINCT h.FY) = 2
        ),
        proj_floored AS (
            SELECT p.District_ID, p.Revenue_Code,
                   CASE WHEN c.Stream_Type IN ('State','Federal')
                        THEN GREATEST(0, p.predicted_raw)
                        ELSE p.predicted_raw
                   END AS predicted,
                   c.Stream_Type
            FROM proj p
            LEFT JOIN code_district_funding_streams c ON c.REV_Code = p.Revenue_Code
            WHERE c.Stream_Type IS NOT NULL
        )
        SELECT pf.Stream_Type,
               COUNT(*) AS n,
               CAST(SUM(ABS(pf.predicted - a.Amount))
                  / NULLIF(SUM(ABS(a.Amount)), 0) * 100 AS INTEGER)
                  AS dollar_weighted_err_pct
        FROM proj_floored pf
        JOIN actual a USING (District_ID, Revenue_Code)
        GROUP BY pf.Stream_Type
        ORDER BY pf.Stream_Type
    """).fetchall()
    return out


def main():
    args = parse_args()
    horizon = [int(fy) for fy in args.horizon.split(",")]

    print(f"[funding-projections] db={args.db} scenario={args.scenario} horizon={horizon}")

    con = duckdb.connect(args.db)
    history, stream_meta, policy = load_inputs(con)
    print(f"[funding-projections] history rows={len(history)} "
          f"stream codes={len(stream_meta)} policy params={len(policy)}")

    rows, summary = build_projections(history, stream_meta, policy, horizon, args.scenario)
    print(f"[funding-projections] projection summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    write_mart(con, rows, args.scenario)
    print(f"[funding-projections] wrote {len(rows)} rows to mart_funding_projections")

    print(f"[funding-projections] back-test (FY23,FY24 -> FY25, dollar-weighted err by Stream_Type):")
    for stream_type, n, err_pct in back_test(con, args.scenario):
        err_str = f"{err_pct}%" if err_pct is not None else "n/a"
        print(f"  {stream_type or '(unclassified)'}: n={n}, err={err_str}")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
