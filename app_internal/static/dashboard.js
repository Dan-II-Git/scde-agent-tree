// SCDE Internal Budget Dashboard — frontend wiring.
//
// Four views share the same FY dropdown:
//   "budget"        → FM Budget vs Actuals by Funds Center
//   "fund"          → Agency Budget by Fund (BEx authoritative budget)
//   "commitments"   → H630 Open POs (BEx Open Encumbrances)
//   "expenditures"  → FI Ledger Expenditures (5xxx GL)
//
// Office drill:
//   Clicking an .ib-office-drill anchor inside the budget view navigates
//   the output pane to /api/report/office?division=X&office=Y&fy=Z.
//
// Side panel:
//   openSidePanel(fc, panel, fy) loads /api/panel/vendors or
//   /api/panel/commitments into the right-side drawer.

const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const fyEl     = document.getElementById("fy");

let YEARS    = [];
let FY_META  = {};   // { 2025: {status, as_of_date}, 2026: {...} }
let CURRENT_FY = null;

(async function init() {
  try {
    const [h, ys] = await Promise.all([
      fetch("/health").then((r) => r.json()),
      fetch("/api/years").then((r) => r.json()),
    ]);
    if (!h.db_exists) {
      setStatus("err", "db missing");
      return;
    }
    YEARS = ys.fys || [];
    if (!YEARS.length) {
      setStatus("err", "no FM data loaded");
      return;
    }
    CURRENT_FY = ys.default || YEARS.at(-1);
    FY_META    = h.fy_status || {};

    // Status line: show partial indicator if latest FY is partial
    const latestMeta = FY_META[String(CURRENT_FY)] || {};
    const partialTag = latestMeta.status === "Partial"
      ? ` · YTD through ${latestMeta.as_of_date || "?"}`
      : "";
    setStatus("ok", `FY${YEARS[0]}–FY${YEARS.at(-1)}${partialTag}`);

    fyEl.innerHTML = YEARS.map((fy) => {
      const meta = FY_META[String(fy)] || {};
      const tag  = meta.status === "Partial" ? " (YTD)" : "";
      return `<option value="${fy}">FY${fy}${tag}</option>`;
    }).join("");
    fyEl.value = CURRENT_FY;

    fyEl.addEventListener("change", () => loadActiveView());
    document.querySelectorAll('input[name="view"]').forEach((r) =>
      r.addEventListener("change", () => { syncGroupByVisibility(); loadActiveView(); })
    );
    document.querySelectorAll('input[name="groupby"]').forEach((r) =>
      r.addEventListener("change", () => loadActiveView())
    );
    syncGroupByVisibility();

    // Build side panel DOM (once, at init)
    buildSidePanel();

    loadActiveView();
  } catch (e) {
    console.error(e);
    setStatus("err", "init failed");
  }
})();

function setStatus(kind, msg) {
  statusEl.className = "status " + kind;
  statusEl.textContent = msg;
}

function activeView() {
  return document.querySelector('input[name="view"]:checked').value;
}

function activeGroupBy() {
  const el = document.querySelector('input[name="groupby"]:checked');
  return el ? el.value : "org";
}

function activeFy() {
  return parseInt(fyEl.value, 10);
}

// The "Group by" radio is only meaningful for the Budget vs Actuals tab.
// Hide it elsewhere so users don't think it applies to other views.
function syncGroupByVisibility() {
  const groupbyEl = document.getElementById("groupby-tabs");
  if (!groupbyEl) return;
  groupbyEl.style.visibility = activeView() === "budget" ? "visible" : "hidden";
}

async function loadActiveView() {
  const view = activeView();
  const fy   = activeFy();
  if (view === "expenditures")  return loadFiExpenditures(fy);
  if (view === "fund")          return loadBudgetByFund(fy);
  if (view === "commitments")   return loadOpenCommitments(fy);
  return loadAgency(fy);
}

// ── FM Budget vs Actuals by Funds Center or Functional Area ──

async function loadAgency(fy) {
  const groupby = activeGroupBy();
  if (groupby === "fa") return loadAgencyByFA(fy);
  outputEl.innerHTML = '<div class="output-loading">Loading FM Budget vs Actuals…</div>';
  try {
    const html = await fetch(`/api/report/budget-vs-actuals?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
    // Row click drills into FC detail — but the FA toggle button needs
    // to swallow the click before the row handler navigates away.
    bindFaToggles();
    bindRowClicks(".ib-fc-table tbody tr[data-fc].ib-fc-row", "fc", (fc) => loadFundsCenter(fc, fy));
    bindOfficeDrills(fy);
  } catch (e) { showError(e.message); }
}

// Click the ▶ toggle on a FC row to reveal/hide its FA breakdown.
// stopPropagation prevents the parent row's drill-into-detail handler.
function bindFaToggles() {
  outputEl.querySelectorAll("button.ib-fa-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const fc = btn.dataset.fc;
      const detailRow = outputEl.querySelector(`tr.ib-fa-detail[data-fc="${CSS.escape(fc)}"]`);
      if (!detailRow) return;
      const expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      btn.classList.toggle("expanded", !expanded);
      if (expanded) {
        detailRow.setAttribute("hidden", "");
      } else {
        detailRow.removeAttribute("hidden");
      }
    });
  });
}

async function loadAgencyByFA(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading FM Budget vs Actuals by Functional Area…</div>';
  try {
    const html = await fetch(`/api/report/budget-vs-actuals-by-fa?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
  } catch (e) { showError(e.message); }
}

// ── Office drill (new) ──

function bindOfficeDrills(fy) {
  outputEl.querySelectorAll("a.ib-office-drill").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const division = a.dataset.division;
      const office   = a.dataset.office;
      loadOfficeDetail(division, office, fy);
    });
  });
}

async function loadOfficeDetail(division, office, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(office)}…</div>`;
  try {
    const url = `/api/report/office?division=${encodeURIComponent(division)}&office=${encodeURIComponent(office)}&fy=${fy}`;
    const html = await fetch(url).then(r => r.text());
    outputEl.innerHTML = html;
    executeInlineScripts(outputEl);
  } catch (e) { showError(e.message); }
}

async function loadFundsCenter(fc, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(fc)}…</div>`;
  try {
    const html = await fetch(`/api/report/funds-center?funds_center=${encodeURIComponent(fc)}&fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = `
      <div class="ib-back"><a href="#" id="back-link">&#8592; Back to all Funds Centers</a></div>
      ${html}
    `;
    executeInlineScripts(outputEl);
    document.getElementById("back-link").addEventListener("click", (e) => {
      e.preventDefault();
      loadAgency(fy);
    });
  } catch (e) { showError(e.message); }
}

// ── Agency Budget by Fund ──

async function loadBudgetByFund(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading Agency Budget by Fund…</div>';
  try {
    const html = await fetch(`/api/report/budget-by-fund?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
  } catch (e) { showError(e.message); }
}

// ── H630 Open Commitments ──

async function loadOpenCommitments(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading H630 Open Commitments…</div>';
  try {
    const html = await fetch(`/api/report/open-commitments?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
  } catch (e) { showError(e.message); }
}

// ── FI Ledger Expenditures ──

async function loadFiExpenditures(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading FI Ledger Expenditures…</div>';
  try {
    const html = await fetch(`/api/report/fi-expenditures?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
    bindRowClicks(".ib-fc-table tbody tr[data-cc]", "cc", (cc) => loadCostCenterDetail(cc, fy));
  } catch (e) { showError(e.message); }
}

async function loadCostCenterDetail(cc, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(cc)}…</div>`;
  try {
    const html = await fetch(`/api/report/fi-expenditures/cost-center?cost_center=${encodeURIComponent(cc)}&fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = `
      <div class="ib-back"><a href="#" id="back-link">&#8592; Back to all cost centers</a></div>
      ${html}
    `;
    document.getElementById("back-link").addEventListener("click", (e) => {
      e.preventDefault();
      loadFiExpenditures(fy);
    });
  } catch (e) { showError(e.message); }
}

// ── Side Panel ──

function buildSidePanel() {
  if (document.getElementById("ib-side-panel")) return; // already built

  const backdrop = document.createElement("div");
  backdrop.id = "ib-side-panel-backdrop";
  backdrop.className = "ib-side-panel-backdrop";
  backdrop.addEventListener("click", closeSidePanel);

  const panel = document.createElement("div");
  panel.id = "ib-side-panel";
  panel.className = "ib-side-panel";
  panel.innerHTML = `
    <div class="ib-side-panel-header">
      <span class="ib-side-panel-title" id="ib-panel-title"></span>
      <button class="ib-side-panel-close" id="ib-panel-close" aria-label="Close panel">&#10005;</button>
    </div>
    <div class="ib-side-panel-body" id="ib-panel-body">
      <div class="output-loading">Loading…</div>
    </div>
  `;
  document.body.appendChild(backdrop);
  document.body.appendChild(panel);

  document.getElementById("ib-panel-close").addEventListener("click", closeSidePanel);

  // ESC key closes
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidePanel();
  });
}

function openSidePanel(fc, panelType, fy) {
  const backdrop = document.getElementById("ib-side-panel-backdrop");
  const panel    = document.getElementById("ib-side-panel");
  const title    = document.getElementById("ib-panel-title");
  const body     = document.getElementById("ib-panel-body");

  if (!panel) return;

  const panelLabel = panelType === "vendors" ? "Vendors Paid" : "Open Commitments";
  title.textContent = `${panelLabel} — ${fc} FY${fy}`;
  body.innerHTML = '<div class="output-loading">Loading…</div>';

  backdrop.classList.add("active");
  panel.classList.add("open");

  const url = `/api/panel/${panelType}?funds_center=${encodeURIComponent(fc)}&fy=${fy}`;
  fetch(url)
    .then(r => r.text())
    .then(html => { body.innerHTML = html; executeInlineScripts(body); })
    .catch(err => { body.innerHTML = `<div class="output-error">${escapeHtml(err.message)}</div>`; });
}

function closeSidePanel() {
  const backdrop = document.getElementById("ib-side-panel-backdrop");
  const panel    = document.getElementById("ib-side-panel");
  if (!panel) return;
  backdrop.classList.remove("active");
  panel.classList.remove("open");
}

// ── Utilities ──

// Browsers do NOT execute <script> tags inserted via innerHTML. Call this
// after every innerHTML assignment that may contain inline <script> blocks
// (office page, FC detail page, side panel fragments) to re-create the
// scripts as real elements so the browser runs them.
function executeInlineScripts(container) {
  container.querySelectorAll("script").forEach((oldScript) => {
    const newScript = document.createElement("script");
    for (const attr of oldScript.attributes) newScript.setAttribute(attr.name, attr.value);
    newScript.textContent = oldScript.textContent;
    oldScript.replaceWith(newScript);
  });
}

function bindRowClicks(selector, dataKey, handler) {
  outputEl.querySelectorAll(selector).forEach((tr) => {
    tr.addEventListener("click", () => handler(tr.dataset[dataKey]));
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function showError(msg) {
  outputEl.innerHTML = `<div class="output-error">${escapeHtml(msg)}</div>`;
}
