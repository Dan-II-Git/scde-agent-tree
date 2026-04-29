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
    """
    history = con.execute(f"""
        SELECT District_ID, Revenue_Code, FY, CAST(Amount AS DOUBLE) AS Amount
        FROM lea_revenues
        WHERE Reported_Flag = TRUE
          AND Amount IS NOT NULL
          AND Amount != 0
          AND FY BETWEEN {HISTORY_MIN_FY} AND {HISTORY_MAX_FY}
    """).fetchall()

    stream_meta = {}
    for code, stream_type, alloc_basis, sunset_note in con.execute("""
        SELECT REV_Code, Stream_Type, Allocation_Basis, Sunset_Note
        FROM code_district_funding_streams
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
    n_formula = n_trend_3fy = n_trend_2fy = n_sunset = n_insufficient = n_unknown_code = 0

    for (district_id, code), pts in series.items():
        meta = stream_meta.get(code)
        stream_type = meta["stream_type"] if meta else None
        alloc_basis = meta["allocation_basis"] if meta else None
        sunset_fy = meta["sunset_fy"] if meta else None
        if meta is None:
            n_unknown_code += 1

        pts.sort()
        fys, amts = zip(*pts)
        fit = fit_linear_trend(fys, amts) if len(pts) >= 2 else None

        for proj_fy in horizon:
            # Sunset rule wins
            if sunset_fy is not None and proj_fy > sunset_fy:
                rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                                 0.0, 0.0, 0.0, "sunset_zero", scenario, built_at))
                n_sunset += 1
                continue

            # Insufficient history
            if fit is None:
                rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                                 None, None, None, "insufficient_history", scenario, built_at))
                n_insufficient += 1
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
            if fit["n"] >= 3:
                n_trend_3fy += 1
            else:
                n_trend_2fy += 1
            rows.append(_row(district_id, proj_fy, code, stream_type, alloc_basis,
                             point, lower, upper, method, scenario, built_at))

    summary = {
        "rows": len(rows),
        "trend_3fy": n_trend_3fy,
        "trend_2fy": n_trend_2fy,
        "sunset_zero": n_sunset,
        "insufficient_history": n_insufficient,
        "formula_sac": n_formula,
        "unknown_code_combos": n_unknown_code,
    }
    return rows, summary


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
    Refit on FY23-FY24, predict FY25, compare to FY25 actuals (Reported_Flag=TRUE
    only). Returns MAPE per Method for each Stream_Type.
    """
    out = con.execute(f"""
        WITH hist AS (
            SELECT District_ID, Revenue_Code, FY, CAST(Amount AS DOUBLE) AS Amount
            FROM lea_revenues
            WHERE Reported_Flag = TRUE
              AND Amount IS NOT NULL AND Amount != 0
              AND FY IN (2023, 2024)
        ),
        actual AS (
            SELECT District_ID, Revenue_Code, CAST(Amount AS DOUBLE) AS Amount
            FROM lea_revenues
            WHERE Reported_Flag = TRUE
              AND Amount IS NOT NULL AND Amount != 0
              AND FY = 2025
        ),
        proj AS (
            SELECT h.District_ID, h.Revenue_Code,
                   -- 2-point projection: FY25 = 2*FY24 - FY23 (linear extrapolation)
                   2 * MAX(CASE WHEN h.FY = 2024 THEN h.Amount END)
                     - MAX(CASE WHEN h.FY = 2023 THEN h.Amount END) AS predicted
            FROM hist h
            GROUP BY 1, 2
            HAVING COUNT(DISTINCT h.FY) = 2
        )
        SELECT c.Stream_Type,
               COUNT(*) AS n,
               AVG(ABS(p.predicted - a.Amount) / NULLIF(ABS(a.Amount), 0)) AS mape
        FROM proj p
        JOIN actual a USING (District_ID, Revenue_Code)
        LEFT JOIN code_district_funding_streams c ON c.REV_Code = p.Revenue_Code
        GROUP BY c.Stream_Type
        ORDER BY c.Stream_Type
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

    print(f"[funding-projections] back-test (FY23,FY24 -> FY25, MAPE by Stream_Type):")
    for stream_type, n, mape in back_test(con, args.scenario):
        mape_str = f"{mape:.1%}" if mape is not None else "n/a"
        print(f"  {stream_type or '(unclassified)'}: n={n}, MAPE={mape_str}")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
