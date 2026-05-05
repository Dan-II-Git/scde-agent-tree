// SCDE Internal Budget Dashboard — frontend wiring.
//
// Two views share the same FY dropdown:
//   - "budget"        → FM Budget vs Actuals (sceis_fmeddw + view)
//   - "expenditures"  → FI ledger expenditures (5xxx GL)

const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const fyEl     = document.getElementById("fy");

let YEARS = [];
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
      setStatus("err", "no FMEDDW data loaded");
      return;
    }
    CURRENT_FY = ys.default || YEARS.at(-1);
    setStatus("ok", `FMEDDW: FY${YEARS[0]}–FY${YEARS.at(-1)}`);
    fyEl.innerHTML = YEARS.map((fy) => `<option value="${fy}">FY${fy}</option>`).join("");
    fyEl.value = CURRENT_FY;

    fyEl.addEventListener("change", () => loadActiveView());
    document.querySelectorAll('input[name="view"]').forEach((r) =>
      r.addEventListener("change", () => loadActiveView())
    );

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

function activeFy() {
  return parseInt(fyEl.value, 10);
}

async function loadActiveView() {
  const view = activeView();
  if (view === "expenditures") return loadFiExpenditures(activeFy());
  return loadAgency(activeFy());
}

async function loadAgency(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading FM Budget vs Actuals…</div>';
  try {
    const html = await fetch(`/api/report/budget-vs-actuals?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
    bindRowClicks(".ib-fc-table tbody tr[data-fc]", "fc", (fc) => loadFundsCenter(fc, fy));
  } catch (e) { showError(e.message); }
}

async function loadFiExpenditures(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading FI Ledger Expenditures…</div>';
  try {
    const html = await fetch(`/api/report/fi-expenditures?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
    bindRowClicks(".ib-fc-table tbody tr[data-cc]", "cc", (cc) => loadCostCenterDetail(cc, fy));
  } catch (e) { showError(e.message); }
}

async function loadFundsCenter(fc, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(fc)}…</div>`;
  try {
    const html = await fetch(`/api/report/funds-center?funds_center=${encodeURIComponent(fc)}&fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = `
      <div class="ib-back"><a href="#" id="back-link">← Back to all funds centers</a></div>
      ${html}
    `;
    document.getElementById("back-link").addEventListener("click", (e) => {
      e.preventDefault();
      loadAgency(fy);
    });
  } catch (e) { showError(e.message); }
}

async function loadCostCenterDetail(cc, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(cc)}…</div>`;
  try {
    const html = await fetch(`/api/report/fi-expenditures/cost-center?cost_center=${encodeURIComponent(cc)}&fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = `
      <div class="ib-back"><a href="#" id="back-link">← Back to all cost centers</a></div>
      ${html}
    `;
    document.getElementById("back-link").addEventListener("click", (e) => {
      e.preventDefault();
      loadFiExpenditures(fy);
    });
  } catch (e) { showError(e.message); }
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
