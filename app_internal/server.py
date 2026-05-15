"""SCDE Internal Budget Dashboard — FastAPI app on port 8766.

Audience: SCDE agency directors. Backed by BEx tables + sceis_fmeddw +
vw_budget_vs_actuals_by_fund + vw_budget_vs_actuals_by_funds_center.
Owned by the internal-budget agent.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app_internal import queries as q
from app_internal import render as r
from app_internal.fund_metadata import get_fund_restriction, RESTRICTION_TYPE_LABEL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scde.internal")

app = FastAPI(title="SCDE Internal Budget Dashboard")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    fys = q.list_fiscal_years()
    return {
        "status":       "ok",
        "db_exists":    (PROJECT_ROOT / "db" / "scde.duckdb").exists(),
        "fmeddw_fys":   fys,
        "fy_status":    {str(fy): q.get_fiscal_year_status(fy) for fy in fys},
    }


@app.get("/api/years")
def api_years() -> JSONResponse:
    fys = q.list_fiscal_years()
    return JSONResponse({"fys": fys, "default": fys[-1] if fys else None})


@app.get("/api/fy-status")
def api_fy_status(fy: int = Query(...)) -> JSONResponse:
    return JSONResponse(q.get_fiscal_year_status(fy))


@app.get("/api/funds-centers")
def api_funds_centers(fy: int = Query(...)) -> JSONResponse:
    return JSONResponse(q.list_funds_centers(fy))


# ── Fund-name lookup from dim_fund_mapping.json ──
import json as _json

_FUND_MAPPING_PATH = PROJECT_ROOT / "db" / "dim_fund_mapping.json"
_FUND_CODE_TO_NAME: dict[str, str] = {}

try:
    _raw = _json.loads(_FUND_MAPPING_PATH.read_text(encoding="utf-8"))
    for name, meta in _raw.get("mapping", {}).items():
        code = meta.get("Fund_Code")
        if code:
            _FUND_CODE_TO_NAME[code] = name
except Exception as _exc:
    log.warning("Could not load dim_fund_mapping.json: %s", _exc)


def _resolve_fc_funds(funds_center: str, fy: int) -> list[dict]:
    """Return top-3 fund dicts for a FC with fund name + restriction resolved."""
    raw = q.get_fc_primary_funds(funds_center, fy, top_n=3)
    out = []
    for item in raw:
        code = item["fund_code"]
        fund_name = _FUND_CODE_TO_NAME.get(code, code)
        restriction = get_fund_restriction(fund_name)
        out.append({
            "fund_code":        code,
            "fund_name":        fund_name,
            "actuals":          item["actuals"],
            "restriction_type": RESTRICTION_TYPE_LABEL.get(restriction["type"], restriction["type"]),
            "restriction_text": restriction["text"],
        })
    return out


# ── FM Budget vs Actuals — Funds Center grain (existing + extended) ──

@app.get("/api/report/budget-vs-actuals")
def api_budget_vs_actuals(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    totals = q.get_agency_totals(fy)
    rows = q.get_budget_vs_actuals(fy)
    fa_by_fc = q.get_fc_fa_breakdown(fy)
    fy_meta = q.get_fiscal_year_status(fy)
    return HTMLResponse(r.render_budget_vs_actuals(fy, totals, rows, fy_meta, fa_by_fc))


@app.get("/api/report/budget-vs-actuals-by-fa")
def api_budget_vs_actuals_by_fa(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    totals  = q.get_fa_agency_totals(fy)
    rows    = q.get_budget_vs_actuals_by_functional_area(fy)
    fy_meta = q.get_fiscal_year_status(fy)
    return HTMLResponse(r.render_budget_vs_actuals_by_fa(fy, totals, rows, fy_meta))


@app.get("/api/report/funds-center")
def api_funds_center_detail(
    funds_center: str = Query(...),
    fy: int = Query(...),
) -> HTMLResponse:
    summary = q.get_funds_center_summary(funds_center, fy)
    if summary is None:
        budget_items: list = []
        actuals_items: list = []
        bex_items: list = []
        enc_lines: list = []
        vendor_summary: list = []
        vendor_invoices: list = []
    else:
        budget_items    = q.get_budget_by_commitment_item(funds_center, fy)
        actuals_items   = q.get_actuals_by_commitment_item(funds_center, fy)
        bex_items       = q.get_expense_detail_by_commitment_item(funds_center, fy)
        enc_lines       = q.get_encumbrance_lines(funds_center, fy)
        vendor_summary  = q.get_vendor_payments_summary(funds_center, fy)
        vendor_invoices = q.get_vendor_invoice_detail(funds_center, fy)
    return HTMLResponse(
        r.render_funds_center_detail(
            funds_center, fy, summary,
            budget_items, actuals_items,
            bex_items, enc_lines,
            vendor_summary, vendor_invoices,
        )
    )


# ── New: Agency Budget by Fund panel ──

@app.get("/api/report/budget-by-fund")
def api_budget_by_fund(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    totals  = q.get_fund_agency_totals(fy)
    rows    = q.get_budget_vs_actuals_by_fund(fy)
    fy_meta = q.get_fiscal_year_status(fy)
    return HTMLResponse(r.render_budget_by_fund(fy, totals, rows, fy_meta))


# ── New: Open Commitments panel ──

@app.get("/api/report/open-commitments")
def api_open_commitments(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    rows    = q.get_encumbrances_by_funds_center(fy)
    fy_meta = q.get_fiscal_year_status(fy)
    return HTMLResponse(r.render_open_commitments(fy, rows, fy_meta))


@app.get("/api/report/open-commitments/lines")
def api_commitment_lines(
    funds_center: str = Query(...),
    fy: int = Query(...),
) -> HTMLResponse:
    lines = q.get_encumbrance_lines(funds_center, fy)
    return HTMLResponse(r.render_encumbrance_lines(funds_center, fy, lines))


# ── FI ledger — separate from FM Budget vs Actuals ──

@app.get("/api/report/fi-expenditures")
def api_fi_expenditures(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fi_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} has no 5xxx ledger rows; got {fys}")
    totals = q.get_fi_agency_totals(fy)
    rows = q.get_fi_expenditures_by_cost_center(fy)
    return HTMLResponse(r.render_fi_expenditures(fy, totals, rows))


@app.get("/api/report/fi-expenditures/cost-center")
def api_fi_cost_center_detail(
    cost_center: str = Query(...),
    fy: int = Query(...),
) -> HTMLResponse:
    data = q.get_cost_center_handbook_breakdown(cost_center, fy)
    return HTMLResponse(r.render_cost_center_handbook_detail(cost_center, fy, data))


# ── New: Office detail page ──

@app.get("/api/report/office")
def api_office_detail(
    division: str = Query(...),
    office:   str = Query(...),
    fy:       int = Query(...),
) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    totals   = q.get_office_totals(division, office, fy)
    fc_rows  = q.get_office_fc_rows(division, office, fy)
    fy_meta  = q.get_fiscal_year_status(fy)

    # Build fund lookup: funds_center → list of resolved fund dicts
    fund_lookup: dict[str, list[dict]] = {}
    for row in fc_rows:
        fc = row["funds_center"]
        fund_lookup[fc] = _resolve_fc_funds(fc, fy)

    return HTMLResponse(
        r.render_office_detail(
            division=division,
            office=office,
            fy=fy,
            totals=totals,
            fc_rows=fc_rows,
            fund_lookup=fund_lookup,
            fy_meta=fy_meta,
        )
    )


# ── New: Side-panel fragment endpoints ──

@app.get("/api/panel/vendors")
def api_panel_vendors(
    funds_center: str = Query(...),
    fy:           int = Query(...),
) -> HTMLResponse:
    # Get FC name for the panel header
    summary = q.get_funds_center_summary(funds_center, fy)
    fc_name = summary["name"] if summary else funds_center
    vendor_summary  = q.get_vendor_payments_summary(funds_center, fy)
    vendor_invoices = q.get_vendor_invoice_detail(funds_center, fy)
    return HTMLResponse(
        r.render_panel_vendors(
            funds_center=funds_center,
            fc_name=fc_name,
            fy=fy,
            vendor_summary=vendor_summary,
            vendor_invoices=vendor_invoices,
        )
    )


@app.get("/api/panel/commitments")
def api_panel_commitments(
    funds_center: str = Query(...),
    fy:           int = Query(...),
) -> HTMLResponse:
    summary = q.get_funds_center_summary(funds_center, fy)
    fc_name = summary["name"] if summary else funds_center
    enc_lines = q.get_encumbrance_lines(funds_center, fy)
    return HTMLResponse(
        r.render_panel_commitments(
            funds_center=funds_center,
            fc_name=fc_name,
            fy=fy,
            enc_lines=enc_lines,
        )
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn
    uvicorn.run("app_internal.server:app", host="127.0.0.1", port=8766,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
