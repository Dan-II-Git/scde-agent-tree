// SCDE Finance Dashboard — frontend wiring.

const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");

let DISTRICTS = [];
let YEARS = { lea: [], sceis: [], current_sceis: null };
let WHATIF = { base_fy: null, available_fys: [] };
let MAP = null;
let GEO_LAYER = null;

// ──────────────────────────────────────────────────────────────────────
// Bootstrap
// ──────────────────────────────────────────────────────────────────────

(async function init() {
  try {
    const [h, ds, ys] = await Promise.all([
      fetch("/health").then((r) => r.json()),
      fetch("/api/districts").then((r) => r.json()),
      fetch("/api/years").then((r) => r.json()),
    ]);
    if (!h.db_exists) {
      setStatus("err", "db missing");
      return;
    }
    DISTRICTS = ds;
    YEARS = ys;
    setStatus("ok", `LEA: FY${ys.lea[0]}–FY${ys.lea.at(-1)} · SCEIS: FY${ys.sceis[0]}–FY${ys.sceis.at(-1)}`);
    await populateDropdowns();
    initMap();
    bindActions();
    // Default report: Single-FY Comparison (table mode) for the latest FY.
    // Runs after dropdowns are populated so map-fy and the table radio
    // already hold their default values.
    runReport("compare").catch((e) => console.error("default report failed:", e));
  } catch (exc) {
    setStatus("err", "init failed");
    console.error(exc);
  }
})();

function setStatus(kind, msg) {
  statusEl.className = "status " + kind;
  statusEl.textContent = msg;
}

async function populateDropdowns() {
  const districtOpts = DISTRICTS.map(
    (d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`,
  ).join("");
  document.getElementById("map-district").innerHTML = districtOpts;
  // Default to Greenville if present
  const greenville = DISTRICTS.find((d) => /greenville/i.test(d.name));
  if (greenville) {
    document.getElementById("map-district").value = greenville.id;
  }

  // FY dropdown is shared by map, district report, and compare. Initial
  // population uses LEA FYs (matches default report-type=detail). The
  // report-type radio handler swaps in SCEIS FYs when YTD is selected.
  populateMapFy("detail");

  // Cache What-If defaults so the header button can launch the report
  // without its own FY dropdown. The What-If page itself lets the user
  // pick a different base FY once it opens.
  try {
    const wd = await fetch("/api/whatif/sac/defaults").then((r) => r.json());
    WHATIF.base_fy = wd.base_fy ?? null;
    WHATIF.available_fys = wd.available_fys || [];
  } catch (e) {
    // dashboard still renders even if the What-If endpoint is unreachable
  }
}

// Swap the FY dropdown options to match the selected report-type, since
// YTD is keyed off SCEIS FYs (which can extend past the latest LEA FY).
function populateMapFy(reportType) {
  const fyEl = document.getElementById("map-fy");
  const prev = fyEl.value;
  if (reportType === "ytd") {
    fyEl.innerHTML = YEARS.sceis
      .map((fy) => `<option value="${fy}">FY${fy}</option>`)
      .join("");
    fyEl.value = YEARS.sceis.includes(parseInt(prev, 10))
      ? prev
      : (YEARS.current_sceis ?? YEARS.sceis.at(-1));
  } else {
    fyEl.innerHTML = YEARS.lea
      .map((fy) => `<option value="${fy}">FY${fy}</option>`)
      .join("");
    fyEl.value = YEARS.lea.includes(parseInt(prev, 10)) ? prev : YEARS.lea.at(-1);
  }
}

// ──────────────────────────────────────────────────────────────────────
// Map
// ──────────────────────────────────────────────────────────────────────

function initMap() {
  MAP = L.map("map", {
    center: [33.85, -81.0],
    zoom: 7,
    dragging: false,
    scrollWheelZoom: false,
    touchZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    zoomControl: false,
    attributionControl: false,
  });
  // No basemap — district polygons are the entire visual; rendered on the
  // neutral background defined in dashboard.css (#map). Removes street-level
  // detail outside SC that distracted from the data.

  document.getElementById("map-fy").addEventListener("change", (e) => loadMap(parseInt(e.target.value, 10)));
  window.addEventListener("resize", () => {
    if (MAP && GEO_LAYER) {
      MAP.invalidateSize();
      MAP.fitBounds(GEO_LAYER.getBounds(), { padding: [8, 8] });
    }
  });
  loadMap(parseInt(document.getElementById("map-fy").value, 10));
}

async function loadMap(fy) {
  try {
    const fc = await fetch(`/api/map?fy=${fy}`).then((r) => r.json());
    if (GEO_LAYER) MAP.removeLayer(GEO_LAYER);
    const values = fc.features
      .map((f) => f.properties.revenue_per_pupil)
      .filter((v) => v != null && Number.isFinite(v));
    const breaks = quintileBreaks(values);
    GEO_LAYER = L.geoJSON(fc, {
      style: (feat) => ({
        className: "district-poly",
        fillColor: colorFor(feat.properties.revenue_per_pupil, breaks),
        color: "#fff",
        weight: 1,
        fillOpacity: 0.78,
      }),
      onEachFeature: (feat, layer) => {
        const p = feat.properties;
        const tooltip = `
          <div class="map-tooltip">
            <strong>${escapeHtml(p.District_Name)}</strong> <small>(${escapeHtml(p.District_ID)})</small><br>
            Revenue: <span class="num">${fmtMoney(p.total_revenue)}</span><br>
            Membership ADM: <span class="num">${fmtInt(p.membership_adm)}</span><br>
            Per ADM pupil: <span class="num">${fmtMoney(p.revenue_per_pupil)}</span>
          </div>`;
        layer.bindTooltip(tooltip, { sticky: true });
        layer.on("click", () => {
          document.getElementById("map-district").value = p.District_ID;
          // Polygon click runs whichever single-district report the
          // report-type radio currently selects. The map FY only
          // applies if that report uses an FY (detail / YTD).
          const reportType = currentReportType();
          if (reportType !== "ytd") {
            document.getElementById("map-fy").value = fy;
          }
          runReport("district");
        });
      },
    }).addTo(MAP);
    MAP.invalidateSize();
    MAP.fitBounds(GEO_LAYER.getBounds(), { padding: [8, 8] });
    renderLegend(breaks);
  } catch (exc) {
    console.error(exc);
    showError(`Map load failed: ${exc.message}`);
  }
}

function quintileBreaks(values) {
  const sorted = values.slice().sort((a, b) => a - b);
  const n = sorted.length;
  if (n === 0) return [0, 0, 0, 0, 0];
  const q = (p) => sorted[Math.min(n - 1, Math.floor(p * n))];
  return [sorted[0], q(0.2), q(0.4), q(0.6), q(0.8), sorted[n - 1]];
}

const SCALE = ["#E2EAF1", "#B5CADD", "#7E9DBC", "#4D789F", "#234058"];

function colorFor(v, breaks) {
  if (v == null || !Number.isFinite(v)) return "#CBD5E0";
  for (let i = 1; i < breaks.length; i++) {
    if (v <= breaks[i]) return SCALE[Math.min(i - 1, SCALE.length - 1)];
  }
  return SCALE[SCALE.length - 1];
}

function renderLegend(breaks) {
  const el = document.getElementById("map-legend");
  if (!breaks || breaks.every((b) => b === 0)) {
    el.innerHTML = '<span>No data for this FY.</span>';
    return;
  }
  const items = SCALE.map((c, i) => {
    const lo = breaks[i];
    const hi = breaks[i + 1];
    return `<span><span class="swatch" style="background:${c}"></span>${fmtMoney(lo)}–${fmtMoney(hi)}</span>`;
  });
  el.innerHTML = "Revenue per ADM pupil:&nbsp; " + items.join("&nbsp;&nbsp;");
}

// ──────────────────────────────────────────────────────────────────────
// Report actions
// ──────────────────────────────────────────────────────────────────────

function bindActions() {
  document.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => runReport(btn.dataset.action));
  });
  // Switching report-type swaps FY options (LEA ↔ SCEIS) and reloads
  // the choropleth so the map matches whichever FY is now active.
  document.querySelectorAll('input[name="report-type"]').forEach((r) => {
    r.addEventListener("change", () => {
      populateMapFy(currentReportType());
      const fy = parseInt(document.getElementById("map-fy").value, 10);
      if (Number.isFinite(fy)) loadMap(fy);
    });
  });
}

function currentReportType() {
  return document.querySelector('input[name="report-type"]:checked').value;
}

function currentCompareMode() {
  return document.querySelector('input[name="compare-mode"]:checked').value;
}

async function runReport(action) {
  let url = "";
  switch (action) {
    case "district": {
      // Single-district report; type comes from the report-type radio.
      // For YTD the Table/Chart radio picks between detail and chart.
      const t = currentReportType();
      const district = qs("map-district");
      const fy = qs("map-fy");
      if (t === "detail") {
        url = `/api/report/detail?district=${district}&fy=${fy}`;
      } else if (t === "multi-fy") {
        url = `/api/report/multi-fy?district=${district}`;
      } else if (t === "ytd") {
        const ytdView = currentCompareMode() === "chart" ? "chart" : "detail";
        url = `/api/ytd/${ytdView}?district=${district}&fy=${fy}`;
      }
      break;
    }
    case "compare":
      url = `/api/report/compare?fy=${qs("map-fy")}&mode=${currentCompareMode()}`;
      break;
    case "whatif-sac": {
      // Prefer whatever FY is currently in the map dropdown if it's a
      // valid What-If base; otherwise fall back to the API-provided
      // default (typically the latest engine-loaded FY).
      const cur = parseInt(document.getElementById("map-fy").value, 10);
      const baseFy = WHATIF.available_fys.includes(cur) ? cur : WHATIF.base_fy;
      const url = baseFy
        ? `/api/whatif/sac/report?base_fy=${baseFy}`
        : `/api/whatif/sac/report`;
      window.open(url, "_blank", "noopener");
      return;
    }
    default:
      return;
  }

  outputEl.innerHTML = '<div class="output-loading">Generating…</div>';
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      const txt = await resp.text();
      showError(`HTTP ${resp.status}: ${txt}`);
      return;
    }
    const html = await resp.text();
    outputEl.innerHTML = html;
    await executeInlineScripts(outputEl);
    outputEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (exc) {
    showError(exc.message);
  }
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

function qs(id) {
  return encodeURIComponent(document.getElementById(id).value);
}

// Re-run <script> tags inserted via innerHTML — the spec marks them inert,
// so Tippy CDN + the info-btn init IIFE never fire without this. External
// srcs are awaited so inline scripts that reference window.tippy run after
// the CDN finishes loading.
async function executeInlineScripts(container) {
  const scripts = Array.from(container.querySelectorAll("script"));
  for (const oldScript of scripts) {
    await new Promise((resolve) => {
      const s = document.createElement("script");
      for (const attr of oldScript.attributes) {
        s.setAttribute(attr.name, attr.value);
      }
      s.text = oldScript.textContent;
      if (oldScript.src) {
        s.onload = resolve;
        s.onerror = resolve;
      }
      oldScript.parentNode.replaceChild(s, oldScript);
      if (!oldScript.src) resolve();
    });
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmtMoney(v) {
  if (v == null || !Number.isFinite(v)) return "n/a";
  const n = Math.round(v);
  if (n === 0) return "$0";
  if (n < 0) return `$(${Math.abs(n).toLocaleString()})`;
  return `$${n.toLocaleString()}`;
}
function fmtInt(v) {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return v.toLocaleString();
}
function showError(msg) {
  outputEl.innerHTML = `<div class="output-error">${escapeHtml(msg)}</div>`;
}
