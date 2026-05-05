// SCDE Internal Budget Dashboard — frontend wiring.

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
    fyEl.addEventListener("change", () => loadAgency(parseInt(fyEl.value, 10)));
    document.querySelector('button[data-action="agency"]')
            .addEventListener("click", () => loadAgency(parseInt(fyEl.value, 10)));
    loadAgency(CURRENT_FY);
  } catch (e) {
    console.error(e);
    setStatus("err", "init failed");
  }
})();

function setStatus(kind, msg) {
  statusEl.className = "status " + kind;
  statusEl.textContent = msg;
}

async function loadAgency(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading agency view…</div>';
  try {
    const html = await fetch(`/api/report/budget-vs-actuals?fy=${fy}`).then(r => r.text());
    outputEl.innerHTML = html;
    bindRowClicks(fy);
  } catch (e) {
    showError(e.message);
  }
}

async function loadFundsCenter(fc, fy) {
  outputEl.innerHTML = `<div class="output-loading">Loading ${escapeHtml(fc)}…</div>`;
  try {
    const html = await fetch(`/api/report/funds-center?funds_center=${encodeURIComponent(fc)}&fy=${fy}`).then(r => r.text());
    // Wrap with a back link
    outputEl.innerHTML = `
      <div class="ib-back"><a href="#" id="back-link">← Back to all funds centers</a></div>
      ${html}
    `;
    document.getElementById("back-link").addEventListener("click", (e) => {
      e.preventDefault();
      loadAgency(fy);
    });
  } catch (e) {
    showError(e.message);
  }
}

function bindRowClicks(fy) {
  outputEl.querySelectorAll(".ib-table tbody tr[data-fc]").forEach((tr) => {
    tr.addEventListener("click", () => loadFundsCenter(tr.dataset.fc, fy));
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
