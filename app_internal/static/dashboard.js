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
      r.addEventListener("change", () => { syncHeaderVisibility(); loadActiveView(); })
    );
    document.querySelectorAll('input[name="groupby"]').forEach((r) =>
      r.addEventListener("change", () => loadActiveView())
    );
    document.querySelectorAll('input[name="rollupmode"]').forEach((r) =>
      r.addEventListener("change", () => loadActiveView())
    );
    syncHeaderVisibility();

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

// The header has two view-specific sub-controls:
//   - "Group by"   visible only on the Budget vs Actuals tab
//   - "Layout"     visible only on the Rollup tab
function syncHeaderVisibility() {
  const view = activeView();
  const gb   = document.getElementById("groupby-tabs");
  const rl   = document.getElementById("rollup-mode-tabs");
  if (gb) gb.style.display = view === "budget" ? ""        : "none";
  if (rl) rl.style.display = view === "rollup" ? ""        : "none";
}

function activeRollupMode() {
  const el = document.querySelector('input[name="rollupmode"]:checked');
  return el ? el.value : "tree";
}

async function loadActiveView() {
  const view = activeView();
  const fy   = activeFy();
  if (view === "rollup")        return loadRollup(fy);
  if (view === "expenditures")  return loadFiExpenditures(fy);
  if (view === "fund")          return loadBudgetByFund(fy);
  if (view === "commitments")   return loadOpenCommitments(fy);
  return loadAgency(fy);
}

// ── Rollup: Org > Fund > FA > CI (Tree + Pivot) ──

let ROLLUP_CACHE = {};  // { fy: { rows, totals, ... } }

async function loadRollup(fy) {
  outputEl.innerHTML = '<div class="output-loading">Loading rollup…</div>';
  try {
    if (!ROLLUP_CACHE[fy]) {
      ROLLUP_CACHE[fy] = await fetch(`/api/report/rollup?fy=${fy}`).then(r => r.json());
    }
    const data = ROLLUP_CACHE[fy];
    const mode = activeRollupMode();
    outputEl.innerHTML = renderRollup(data, mode);
    bindRollupToggles();
  } catch (e) { showError(e.message); }
}

// Hierarchical groupBy that returns {key, label, children, leaves, agg}
// recursively for a chain of accessor functions.
//
// Accessors can set virtual(node) → true to mark a node as a pass-through:
// at flatten time the node is skipped and its children are emitted at the
// parent's level. Used for Sub_Category (Bus Shop / Depot under Transportation):
// the subcat level appears only when sub_category is non-null, otherwise it
// collapses transparently into the office level.
function groupRows(rows, accessors, level = 0) {
  if (level >= accessors.length) return null;
  const acc = accessors[level];
  const m = new Map();
  for (const r of rows) {
    const k = acc.key(r) ?? "(none)";
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  const out = [];
  for (const [k, group] of m) {
    const node = {
      key:    k,
      label:  acc.label(group[0]),
      level:  level,
      kind:   acc.kind,
      code:   acc.code ? acc.code(group[0]) : null,
      agg:    aggregateRows(group),
      leaves: group,
    };
    if (acc.virtual && acc.virtual(node)) node.virtual = true;
    if (level + 1 < accessors.length) {
      node.children = groupRows(group, accessors, level + 1);
    }
    out.push(node);
  }
  // Sort: budget desc, then actuals desc as tie-break, then label
  out.sort((a, b) => {
    const ab = a.agg.current_budget ?? a.agg.actuals;
    const bb = b.agg.current_budget ?? b.agg.actuals;
    if (bb !== ab) return bb - ab;
    return String(a.label).localeCompare(String(b.label));
  });
  return out;
}

function aggregateRows(rows) {
  let b = null, a = 0, anyBudget = false;
  for (const r of rows) {
    if (r.current_budget !== null && r.current_budget !== undefined) {
      b = (b ?? 0) + r.current_budget;
      anyBudget = true;
    }
    a += r.actuals || 0;
  }
  const budget = anyBudget ? b : null;
  return {
    current_budget: budget,
    actuals:        a,
    pct_spent:      (budget && budget > 0) ? a / budget : null,
    true_available: budget !== null ? budget - a : null,
  };
}

function renderRollup(data, mode) {
  const partial = data.fy_status === "Partial"
    ? ` &middot; YTD through ${escapeHtml(data.as_of_date || "?")}`
    : "";
  const header = `
    <div class="ib-report-header">
      <h2>FY${data.fy} Agency Rollup</h2>
      <p class="ib-report-meta">
        Org chart &rarr; Fund &rarr; Functional Area &rarr; Commitment Item${partial}
      </p>
    </div>
    ${renderRollupKpis(data.totals)}
    ${renderCaveatBanner(data)}
  `;
  const body = mode === "pivot"
    ? renderPivot(data)
    : renderTree(data);
  return header + body;
}

function renderRollupKpis(t) {
  const cls = pctClass(t.pct_spent);
  return `
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Appropriated Budget</div>
        <div class="kpi-value">${fmtMoney(t.current_budget)}</div>
        <div class="kpi-sub">BEx Fund-level total · all 20 funds</div></div>
      <div class="kpi"><div class="kpi-label">Actuals</div>
        <div class="kpi-value">${fmtMoney(t.actuals)}</div></div>
      <div class="kpi ${cls}"><div class="kpi-label">% Spent</div>
        <div class="kpi-value">${fmtPct(t.pct_spent)}</div></div>
      <div class="kpi"><div class="kpi-label">Open Encumbrances</div>
        <div class="kpi-value">${fmtMoney(t.open_encumbrances)}</div></div>
      <div class="kpi"><div class="kpi-label">True Available</div>
        <div class="kpi-value">${fmtMoney(t.true_available)}</div></div>
    </div>
  `;
}

function renderCaveatBanner(data) {
  if (!data.caveats || !data.caveats.length) return "";
  const items = data.caveats.map(c => `<li>${escapeHtml(c)}</li>`).join("");
  return `<details class="ib-rollup-caveats"><summary>${data.caveats.length} caveat(s)</summary><ul>${items}</ul></details>`;
}

// ── Tree layout ──

function renderTree(data) {
  const accessors = treeAccessors(data.fa_supported);
  const tree = groupRows(data.rows, accessors);
  const flat = [];
  const flatten = (nodes, parentId, depth) => {
    for (const node of nodes) {
      // Virtual nodes (e.g. null Sub_Category) collapse transparently:
      // emit children at the parent's depth, keeping the parentId.
      if (node.virtual) {
        if (node.children) flatten(node.children, parentId, depth);
        continue;
      }
      const id = parentId ? `${parentId}__${cssSafe(node.key)}` : cssSafe(node.key);
      const hasChildren = !!(node.children && node.children.length);
      flat.push({ node, id, parentId, hasChildren, depth });
      if (hasChildren) flatten(node.children, id, depth + 1);
    }
  };
  flatten(tree, "", 0);

  let body = "";
  for (const r of flat) body += renderFlatRow(r, /* cols */ 1);

  return `
    <table class="ib-table ib-rollup-tree">
      <thead><tr>
        <th>Level</th>
        <th class="num">Current Budget</th>
        <th class="num">Actuals</th>
        <th class="num">% Spent</th>
        <th class="num">True Available</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function renderFlatRow(r, _) {
  const { node, id, parentId, hasChildren, depth } = r;
  // Indent uses the rendered depth (which collapses past virtual nodes),
  // not the raw groupRows level — so Bus Shop at depth=2 lines up with
  // a non-Transportation office's FC at the same visual level.
  const renderedDepth = depth ?? node.level;
  const indent = renderedDepth * 18 + 4;
  const caret = hasChildren
    ? `<button class="ib-tree-caret" data-id="${id}" aria-expanded="false">▶</button>`
    : `<span class="ib-tree-caret-spacer"></span>`;
  const kindTag = `<span class="ib-tree-kind ib-tree-kind-${node.kind}">${node.kind.toUpperCase()}</span>`;
  const pctVal = node.agg.pct_spent;
  const pctCls = pctClass(pctVal);
  const hiddenAttr = parentId ? "hidden" : "";
  return `
    <tr class="ib-tree-row ${hasChildren ? "ib-tree-expandable" : ""}"
        data-id="${id}" data-parent="${parentId}" data-level="${renderedDepth}"
        data-kind="${node.kind}" ${hiddenAttr}>
      <td>
        <span style="display:inline-block; padding-left:${indent}px;">${caret}${kindTag} ${escapeHtml(String(node.label))}</span>
      </td>
      <td class="num">${fmtMoney(node.agg.current_budget)}</td>
      <td class="num">${fmtMoney(node.agg.actuals)}</td>
      <td class="num ${pctCls}">${fmtPct(pctVal)}</td>
      <td class="num">${fmtMoney(node.agg.true_available)}</td>
    </tr>
  `;
}

function treeAccessors(faSupported) {
  const a = [
    { kind: "division", key: r => r.division, label: r => r.division || "(Unknown)" },
    { kind: "office",   key: r => r.division + "||" + r.office,
                        label: r => r.office || "(Office Unknown)" },
    // Sub-Category (e.g. "Bus Shop" / "Depot" under Transportation).
    // Virtualized when sub_category is null so non-Transportation offices
    // render unchanged.
    { kind: "group",    key: r => r.sub_category || "__NONE__",
                        label: r => r.sub_category || "(no sub-category)",
                        virtual: node => node.key === "__NONE__" },
    { kind: "fc",       key: r => r.funds_center,
                        label: r => r.fc_name + " (" + r.funds_center + ")",
                        code: r => r.funds_center },
    { kind: "fund",     key: r => r.fund_code,
                        label: r => r.fund_name + " (" + r.fund_code + ")",
                        code: r => r.fund_code },
  ];
  if (faSupported) {
    a.push({
      kind: "fa", key: r => r.functional_area || "(no FA)",
      label: r => (r.fa_name || r.functional_area || "(no FA)")
                  + (r.fa_category ? "  ·  " + r.fa_category : ""),
      code: r => r.functional_area,
    });
  }
  a.push({
    kind: "ci", key: r => r.commitment_item,
    label: r => r.commitment_item + (r.ci_name ? "  ·  " + r.ci_name : ""),
    code: r => r.commitment_item,
  });
  return a;
}

// ── Pivot layout ── (Org rows × Fund columns; click a fund to drill into FA/CI)

function renderPivot(data) {
  // Build row hierarchy: Division > Office > [Sub_Category] > FC
  // Sub_Category is virtual when null (matches the Tree layout).
  const rowAccessors = [
    { kind: "division", key: r => r.division, label: r => r.division || "(Unknown)" },
    { kind: "office",   key: r => r.division + "||" + r.office,
                        label: r => r.office || "(Office Unknown)" },
    { kind: "group",    key: r => r.sub_category || "__NONE__",
                        label: r => r.sub_category || "(no sub-category)",
                        virtual: node => node.key === "__NONE__" },
    { kind: "fc",       key: r => r.funds_center,
                        label: r => r.fc_name + " (" + r.funds_center + ")" },
  ];
  const rowTree = groupRows(data.rows, rowAccessors);

  // Column dimension: Fund (top N by actuals + actuals total)
  const fundAgg = new Map();
  for (const r of data.rows) {
    const k = r.fund_code;
    const prev = fundAgg.get(k) || { fund_code: k, fund_name: r.fund_name, b: 0, a: 0, hasB: false };
    if (r.current_budget !== null && r.current_budget !== undefined) {
      prev.b += r.current_budget; prev.hasB = true;
    }
    prev.a += r.actuals || 0;
    fundAgg.set(k, prev);
  }
  let fundList = [...fundAgg.values()].sort((a,b) => (b.hasB ? b.b : b.a) - (a.hasB ? a.b : a.a));
  // Cap to top 8 columns, group remainder as "Other"
  const TOP_N = 8;
  const topFunds = fundList.slice(0, TOP_N);
  const otherFunds = fundList.slice(TOP_N);
  const showOther = otherFunds.length > 0;
  const otherCodes = new Set(otherFunds.map(f => f.fund_code));

  // colspan = number of fund columns × 2 (Budget, Actuals) + (Other column × 2 if any)
  const colCount = topFunds.length + (showOther ? 1 : 0);

  // Header rows
  let head = `<thead>
    <tr>
      <th rowspan="2">Org</th>
      ${topFunds.map(f => `<th colspan="2" class="ib-pivot-fund-h">
        <div class="ib-pivot-fund-name">${escapeHtml(f.fund_name)}</div>
        <div class="ib-pivot-fund-code">${escapeHtml(f.fund_code)}</div>
      </th>`).join("")}
      ${showOther ? `<th colspan="2" class="ib-pivot-fund-h"><div class="ib-pivot-fund-name">Other</div><div class="ib-pivot-fund-code">${otherFunds.length} funds</div></th>` : ""}
      <th colspan="2" class="ib-pivot-total-h">TOTAL</th>
    </tr>
    <tr>
      ${topFunds.map(_ => `<th class="num">Budget</th><th class="num">Actuals</th>`).join("")}
      ${showOther ? `<th class="num">Budget</th><th class="num">Actuals</th>` : ""}
      <th class="num">Budget</th><th class="num">Actuals</th>
    </tr>
  </thead>`;

  // Flatten the row tree (virtual nodes collapse transparently)
  const flat = [];
  const flatten = (nodes, parentId, depth) => {
    for (const n of nodes) {
      if (n.virtual) {
        if (n.children) flatten(n.children, parentId, depth);
        continue;
      }
      const id = parentId ? `${parentId}__${cssSafe(n.key)}` : cssSafe(n.key);
      const hasChildren = !!(n.children && n.children.length);
      flat.push({ node: n, id, parentId, hasChildren, depth });
      if (hasChildren) flatten(n.children, id, depth + 1);
    }
  };
  flatten(rowTree, "", 0);

  let body = "<tbody>";
  for (const r of flat) {
    const { node, id, parentId, hasChildren, depth } = r;
    const indent = (depth ?? node.level) * 16 + 4;
    const caret = hasChildren
      ? `<button class="ib-tree-caret" data-id="${id}" aria-expanded="false">▶</button>`
      : `<span class="ib-tree-caret-spacer"></span>`;
    const fundCells = topFunds.map(f => aggregateForFund(node.leaves, f.fund_code));
    const otherCell = showOther ? aggregateForFundSet(node.leaves, otherCodes) : null;
    const totalCell = aggregateRows(node.leaves);
    const cells = [
      ...fundCells.flatMap(c => [fmtMoney(c.current_budget), fmtMoney(c.actuals)]),
      ...(otherCell ? [fmtMoney(otherCell.current_budget), fmtMoney(otherCell.actuals)] : []),
      fmtMoney(totalCell.current_budget),
      fmtMoney(totalCell.actuals),
    ];
    const hiddenAttr = parentId ? "hidden" : "";
    body += `<tr class="ib-tree-row ${hasChildren ? "ib-tree-expandable" : ""}"
                 data-id="${id}" data-parent="${parentId}" data-level="${node.level}"
                 data-kind="${node.kind}" ${hiddenAttr}>
      <td><span style="display:inline-block; padding-left:${indent}px;">${caret}<span class="ib-tree-kind ib-tree-kind-${node.kind}">${node.kind.toUpperCase()}</span> ${escapeHtml(String(node.label))}</span></td>
      ${cells.map(c => `<td class="num">${c}</td>`).join("")}
    </tr>`;
  }
  body += "</tbody>";

  return `<div class="ib-pivot-scroll"><table class="ib-table ib-pivot-table">${head}${body}</table></div>
          <p class="ib-pivot-footnote">Top ${topFunds.length} funds shown as columns; remainder grouped as &ldquo;Other&rdquo;. Switch to <strong>Tree</strong> layout for FA &amp; CI grain.</p>`;
}

function aggregateForFund(rows, fundCode) {
  const sub = rows.filter(r => r.fund_code === fundCode);
  return aggregateRows(sub);
}
function aggregateForFundSet(rows, codeSet) {
  const sub = rows.filter(r => codeSet.has(r.fund_code));
  return aggregateRows(sub);
}

function bindRollupToggles() {
  outputEl.querySelectorAll("button.ib-tree-caret").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id   = btn.dataset.id;
      const tbl  = btn.closest("table");
      if (!id || !tbl) return;
      const open = btn.getAttribute("aria-expanded") === "true";
      if (open) {
        // Collapse: hide all descendants and reset their carets
        collapseDescendants(tbl, id);
        btn.setAttribute("aria-expanded", "false");
        btn.textContent = "▶";
      } else {
        // Expand: show only direct children (their descendants stay hidden)
        tbl.querySelectorAll(`tr[data-parent="${cssAttr(id)}"]`).forEach(row => {
          row.removeAttribute("hidden");
        });
        btn.setAttribute("aria-expanded", "true");
        btn.textContent = "▼";
      }
    });
  });
}

function collapseDescendants(tbl, id) {
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop();
    tbl.querySelectorAll(`tr[data-parent="${cssAttr(cur)}"]`).forEach(row => {
      row.setAttribute("hidden", "");
      const childCaret = row.querySelector("button.ib-tree-caret");
      if (childCaret) {
        childCaret.setAttribute("aria-expanded", "false");
        childCaret.textContent = "▶";
      }
      stack.push(row.dataset.id);
    });
  }
}

// CSS.escape isn't available for attribute-value selectors; we built ids
// with cssSafe so they're already safe for selector use, but quote them
// defensively in case of leading digits.
function cssAttr(s) {
  return String(s).replace(/"/g, '\\"');
}

// ── Money / pct formatters ──

function fmtMoney(v) {
  if (v === null || v === undefined) return '<span class="muted">&mdash;</span>';
  if (v === 0) return "$0";
  const abs = Math.abs(v);
  const s = "$" + Math.round(abs).toLocaleString("en-US");
  return v < 0
    ? `<span class="neg">$(${Math.round(abs).toLocaleString("en-US")})</span>`
    : s;
}
function fmtPct(v) {
  if (v === null || v === undefined) return '<span class="muted">&mdash;</span>';
  return Math.round(v * 1000) / 10 + "%";
}
function pctClass(v) {
  if (v === null || v === undefined) return "consumed-light";
  if (v < 0)    return "consumed-negative";
  if (v < 0.5)  return "consumed-light";
  if (v < 0.85) return "consumed-on-track";
  if (v < 1.0)  return "consumed-warning";
  return "consumed-overspent";
}
function cssSafe(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, "_"); }

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
    bindEncCardToggles();
  } catch (e) { showError(e.message); }
}

function bindEncCardToggles() {
  document.querySelectorAll(".ib-enc-card-header").forEach((h) => {
    h.addEventListener("click", () => {
      const target = document.getElementById(h.dataset.target);
      if (!target) return;
      const open = target.style.display !== "none";
      target.style.display = open ? "none" : "";
      const tog = h.querySelector(".ib-collapsible-toggle");
      if (tog) tog.textContent = open ? "►" : "▼";
    });
  });
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
