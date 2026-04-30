"""SCDE Finance Dashboard — local FastAPI app with menu-driven report builder."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import queries as q
from app import render as r
from app import whatif_sac

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scde.dashboard")

app = FastAPI(title="SCDE Finance Dashboard")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "db_exists": (PROJECT_ROOT / "db" / "scde.duckdb").exists(),
        "lea_fys": q.list_fiscal_years_lea(),
        "sceis_fys": q.list_fiscal_years_sceis(),
        "current_sceis_fy": q.current_sceis_fy(),
    }


# ──────────────────────────────────────────────────────────────────────
# Metadata
# ──────────────────────────────────────────────────────────────────────


@app.get("/api/districts")
async def api_districts() -> JSONResponse:
    return JSONResponse(q.list_districts())


@app.get("/api/years")
async def api_years() -> JSONResponse:
    return JSONResponse({
        "lea": q.list_fiscal_years_lea(),
        "sceis": q.list_fiscal_years_sceis(),
        "current_sceis": q.current_sceis_fy(),
    })


@app.get("/api/map")
async def api_map(fy: int = Query(...)) -> JSONResponse:
    if fy not in q.list_fiscal_years_lea():
        raise HTTPException(400, f"FY{fy} not available; got {q.list_fiscal_years_lea()}")
    return JSONResponse(q.get_map_features(fy))


# ──────────────────────────────────────────────────────────────────────
# Reports — return rendered HTML fragments
# ──────────────────────────────────────────────────────────────────────


@app.get("/api/report/detail")
async def api_detail(district: str = Query(...), fy: int = Query(...)) -> HTMLResponse:
    data = q.get_detail_rows(district, fy)
    return HTMLResponse(r.render_detail(data))


@app.get("/api/report/compare")
async def api_compare(fy: int = Query(...), mode: str = Query("table")) -> HTMLResponse:
    data = q.get_compare_table(fy)
    if mode == "chart":
        return HTMLResponse(r.render_compare_chart(data))
    return HTMLResponse(r.render_compare_table(data))


@app.get("/api/report/multi-fy")
async def api_multi_fy(district: str = Query(...)) -> HTMLResponse:
    data = q.get_multi_fy_district(district)
    return HTMLResponse(r.render_multi_fy(data))


@app.get("/api/ytd/chart")
async def api_ytd_chart(district: str = Query(...), fy: int | None = None) -> HTMLResponse:
    data = q.get_ytd_monthly(district, fy)
    return HTMLResponse(r.render_ytd_chart(data))


@app.get("/api/ytd/detail")
async def api_ytd_detail(district: str = Query(...), fy: int | None = None) -> HTMLResponse:
    data = q.get_ytd_monthly(district, fy)
    return HTMLResponse(r.render_ytd_detail(data))


# ──────────────────────────────────────────────────────────────────────
# What-If: State Aid to Classrooms
# ──────────────────────────────────────────────────────────────────────


@app.get("/api/whatif/sac/defaults")
async def api_whatif_sac_defaults() -> JSONResponse:
    """Statute defaults so the UI can render initial slider values."""
    available_fys = whatif_sac.available_fiscal_years()
    fy_modes = {fy: ("total_only" if whatif_sac.is_total_only_fy(fy) else "categorical")
                for fy in available_fys}
    return JSONResponse({
        "appropriation": whatif_sac.FY26_APPROPRIATION_DEFAULT,
        "state_share_pct": whatif_sac.DEFAULT_STATE_SHARE_PCT,
        "weights": dict(whatif_sac.DEFAULT_WEIGHTS),
        "base_fy": whatif_sac.DEFAULT_BASE_FY,
        "available_fys": available_fys,
        "fy_modes": fy_modes,
        "apply_hold_harmless": True,
        "apply_charter_full_state": True,
        "hold_harmless_baseline_fy": whatif_sac.HOLD_HARMLESS_BASELINE_FY,
        "hold_harmless_revenue_codes": whatif_sac.HOLD_HARMLESS_REVENUE_CODES,
    })


@app.post("/api/whatif/sac")
async def api_whatif_sac(scenario: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
    """Run the strict-formula SAC allocation engine. Body is a partial
    scenario dict; missing fields fall back to statute defaults."""
    try:
        sc = whatif_sac.Scenario.from_dict(scenario or {})
        result = whatif_sac.run_scenario(sc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.get("/api/whatif/sac/report")
async def api_whatif_sac_report(
    base_fy: int = Query(default=whatif_sac.DEFAULT_BASE_FY),
    appropriation: float = Query(default=whatif_sac.FY26_APPROPRIATION_DEFAULT),
) -> HTMLResponse:
    """Render the standalone interactive What-If HTML page on demand."""
    # Lazy-import the builder to avoid pulling sys.path tweaks at server import
    from scripts.build_whatif_sac_report import build_html, _slim_inputs
    inputs = _slim_inputs(base_fy)
    if not inputs:
        raise HTTPException(404, f"No input data for FY{base_fy}")
    return HTMLResponse(build_html(inputs, base_fy, appropriation))


# ──────────────────────────────────────────────────────────────────────
# Static
# ──────────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("app.server:app", host="127.0.0.1", port=8765, reload=False, log_level="info")


if __name__ == "__main__":
    main()
