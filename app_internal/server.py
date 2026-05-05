"""SCDE Internal Budget Dashboard — FastAPI app on port 8766.

Audience: SCDE agency directors. Backed by sceis_fmeddw +
vw_budget_vs_actuals_by_funds_center. Owned by the internal-budget agent.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app_internal import queries as q
from app_internal import render as r

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
    return {
        "status": "ok",
        "db_exists": (PROJECT_ROOT / "db" / "scde.duckdb").exists(),
        "fmeddw_fys": q.list_fiscal_years(),
    }


@app.get("/api/years")
def api_years() -> JSONResponse:
    fys = q.list_fiscal_years()
    return JSONResponse({"fys": fys, "default": fys[-1] if fys else None})


@app.get("/api/funds-centers")
def api_funds_centers(fy: int = Query(...)) -> JSONResponse:
    return JSONResponse(q.list_funds_centers(fy))


@app.get("/api/report/budget-vs-actuals")
def api_budget_vs_actuals(fy: int = Query(...)) -> HTMLResponse:
    fys = q.list_fiscal_years()
    if fy not in fys:
        raise HTTPException(400, f"FY{fy} not loaded; got {fys}")
    totals = q.get_agency_totals(fy)
    rows = q.get_budget_vs_actuals(fy)
    return HTMLResponse(r.render_budget_vs_actuals(fy, totals, rows))


@app.get("/api/report/funds-center")
def api_funds_center_detail(
    funds_center: str = Query(...),
    fy: int = Query(...),
) -> HTMLResponse:
    summary = q.get_funds_center_summary(funds_center, fy)
    if summary is None:
        budget_items: list = []
        actuals_items: list = []
    else:
        budget_items = q.get_budget_by_commitment_item(funds_center, fy)
        actuals_items = q.get_actuals_by_commitment_item(funds_center, fy)
    return HTMLResponse(
        r.render_funds_center_detail(funds_center, fy, summary, budget_items, actuals_items)
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn
    uvicorn.run("app_internal.server:app", host="127.0.0.1", port=8766,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
