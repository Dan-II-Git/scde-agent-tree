// SCDE Finance Dashboard — frontend wiring.

const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");

let DISTRICTS = [];
let YEARS = { lea: [], sceis: [], current_sceis: null };
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
    populateDropdowns();
    initMap();
    bindActions();
  } catch (exc) {
    setStatus("err", "init failed");
    console.error(exc);
  }
})();

function setStatus(kind, msg) {
  statusEl.className = "status " + kind;
  statusEl.textContent = msg;
}

function populateDropdowns() {
  const districtSelects = ["detail-district", "multify-district", "ytd-district"];
  const districtOpts = DISTRICTS.map(
    (d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`,
  ).join("");
  for (const id of districtSelects) {
    document.getElementById(id).innerHTML = districtOpts;
  }
  // Default to Greenville if present
  const greenville = DISTRICTS.find((d) => /greenville/i.test(d.name));
  if (greenville) {
    for (const id of districtSelects) {
      document.getElementById(id).value = greenville.id;
    }
  }

  const leaOpts = YEARS.lea
    .map((fy) => `<option value="${fy}">FY${fy}</option>`)
    .join("");
  document.getElementById("detail-fy").innerHTML = leaOpts;
  document.getElementById("compare-fy").innerHTML = leaOpts;
  document.getElementById("map-fy").innerHTML = leaOpts;

  const sceisOpts = YEARS.sceis
    .map((fy) => `<option value="${fy}">FY${fy}</option>`)
    .join("");
  document.getElementById("ytd-fy").innerHTML = sceisOpts;

  // What-If only supports FYs we have category WPU data for. Hardcoded
  // until lea_wpu_category covers more than FY24.
  document.getElementById("whatif-fy").innerHTML =
    [2024].map((fy) => `<option value="${fy}">FY${fy}</option>`).join("");

  // Defaults: latest FY for LEA selectors, current SCEIS FY for YTD
  const latestLea = YEARS.lea.at(-1);
  document.getElementById("detail-fy").value = latestLea;
  document.getElementById("compare-fy").value = latestLea;
  document.getElementById("map-fy").value = latestLea;
  if (YEARS.current_sceis) document.getElementById("ytd-fy").value = YEARS.current_sceis;
}

// ──────────────────────────────────────────────────────────────────────
// Map
// ──────────────────────────────────────────────────────────────────────

function initMap() {
  MAP = L.map("map", {
    center: [33.85, -81.0],
    zoom: 7,
    minZoom: 6,
    maxZoom: 10,
    scrollWheelZoom: true,
    attributionControl: false,
  });
  // No basemap — district polygons are the entire visual; rendered on the
  // neutral background defined in dashboard.css (#map). Removes street-level
  // detail outside SC that distracted from the data.

  document.getElementById("map-fy").addEventListener("change", (e) => loadMap(parseInt(e.target.value, 10)));
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
            Headcount: <span class="num">${fmtInt(p.headcount)}</span><br>
            Per pupil: <span class="num">${fmtMoney(p.revenue_per_pupil)}</span>
          </div>`;
        layer.bindTooltip(tooltip, { sticky: true });
        layer.on("click", () => {
          document.getElementById("detail-district").value = p.District_ID;
          document.getElementById("detail-fy").value = fy;
          runReport("detail");
        });
      },
    }).addTo(MAP);
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
  el.innerHTML = "Revenue per pupil:&nbsp; " + items.join("&nbsp;&nbsp;");
}

// ──────────────────────────────────────────────────────────────────────
// Report actions
// ──────────────────────────────────────────────────────────────────────

function bindActions() {
  document.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => runReport(btn.dataset.action));
  });
}

async function runReport(action) {
  let url = "";
  switch (action) {
    case "detail":
      url = `/api/report/detail?district=${qs("detail-district")}&fy=${qs("detail-fy")}`;
      break;
    case "compare":
      const mode = document.querySelector('input[name="compare-mode"]:checked').value;
      url = `/api/report/compare?fy=${qs("compare-fy")}&mode=${mode}`;
      break;
    case "multi-fy":
      url = `/api/report/multi-fy?district=${qs("multify-district")}`;
      break;
    case "ytd-chart":
      url = `/api/ytd/chart?district=${qs("ytd-district")}&fy=${qs("ytd-fy")}`;
      break;
    case "ytd-detail":
      url = `/api/ytd/detail?district=${qs("ytd-district")}&fy=${qs("ytd-fy")}`;
      break;
    case "whatif-sac":
      window.open(`/api/whatif/sac/report?base_fy=${qs("whatif-fy")}`, "_blank", "noopener");
      return;
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
