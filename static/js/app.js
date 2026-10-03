/* DataLens front end: uploads the CSV, then draws every section of the report. */
"use strict";

const state = { report: null, id: null, corrMethod: "pearson", crosstab: null, ctMode: "counts" };
const MAX_MB = Number(document.body.dataset.maxMb || 50);
const ALLOWED = [".csv", ".tsv", ".txt"];
const C = { accent: "#1F6E8C", amber: "#C98B12", bad: "#AE4338", good: "#2E7D5B", ink: "#17303C", muted: "#56707A", grid: "#E3EAE9" };
const PALETTE = ["#1F6E8C", "#C98B12", "#2E7D5B", "#AE4338", "#6A5A8C", "#4A9BB5", "#8C6B3F", "#56707A", "#A0527A", "#5E8A3A", "#9AA9AE"];

// ---------------------------------------------------------------------------
// Small DOM helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (typeof value !== "number") return String(value);
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  if (abs >= 1) return value.toLocaleString("en-US", { maximumFractionDigits: digits });
  if (abs === 0) return "0";
  return value.toPrecision(3).replace(/\.?0+$/, "");
}
const pct = (v, d = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(d)}%`);
const dateOnly = (iso) => (iso ? String(iso).slice(0, 10) : "—");
const plural = (n, word) => `${fmt(n)} ${word}${n === 1 ? "" : "s"}`;

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4500);
}

function table(headers, rows, opts = {}) {
  const numeric = new Set(opts.numeric || []);
  const thead = el("thead", {}, el("tr", {}, headers.map((h, i) => el("th", { class: numeric.has(i) ? "num" : null }, h))));
  const tbody = el("tbody");
  rows.forEach((row, rIndex) => {
    const tr = el("tr", { class: opts.onRowClick ? "clickable" : null, tabindex: opts.onRowClick ? "0" : null });
    row.forEach((cell, i) => {
      const isNode = cell instanceof Node;
      const missing = cell === null || cell === undefined;
      const td = el("td", { class: [numeric.has(i) ? "num" : "", missing && opts.markMissing ? "missing" : "", (opts.wrap || []).includes(i) ? "wrap" : ""].join(" ").trim() || null });
      if (isNode) td.append(cell); else td.textContent = missing ? (opts.markMissing ? "" : "—") : String(cell);
      tr.append(td);
    });
    if (opts.onRowClick) {
      tr.addEventListener("click", () => opts.onRowClick(rIndex));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") opts.onRowClick(rIndex); });
    }
    tbody.append(tr);
  });
  return el("div", { class: "table-wrap" }, el("table", {}, thead, tbody));
}

function kpi(value, labelText, tone) {
  return el("div", { class: `kpi ${tone || ""}` }, el("div", { class: "kpi-value" }, value), el("div", { class: "kpi-label" }, labelText));
}

function note(text, level = "info") { return el("div", { class: `note ${level}` }, text); }

function fillSelect(select, options, { blank = null, selected = null } = {}) {
  clear(select);
  if (blank !== null) select.append(el("option", { value: "" }, blank));
  options.forEach((o) => {
    const value = typeof o === "string" ? o : o.value;
    const text = typeof o === "string" ? o : o.label;
    select.append(el("option", { value, selected: value === selected ? true : null }, text));
  });
  if (selected !== null) select.value = selected;
}

// ---------------------------------------------------------------------------
// Charts (Plotly)
// ---------------------------------------------------------------------------
function plot(target, data, layout = {}, config = {}) {
  if (typeof target === "string") target = document.getElementById(target);
  if (!window.Plotly) {
    clear(target).append(el("p", { class: "error-text" }, "Chart unavailable: Plotly did not load."));
    return;
  }
  const axis = { gridcolor: C.grid, zerolinecolor: C.grid, linecolor: C.grid, automargin: true, tickfont: { size: 11 } };
  const base = {
    margin: { l: 56, r: 18, t: 16, b: 48 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: getComputedStyle(document.body).fontFamily, size: 12, color: C.ink },
    colorway: PALETTE, showlegend: false, hoverlabel: { font: { size: 12 } },
  };
  const merged = Object.assign({}, base, layout);
  merged.xaxis = Object.assign({}, axis, layout.xaxis || {});
  merged.yaxis = Object.assign({}, axis, layout.yaxis || {});
  Plotly.newPlot(target, data, merged, Object.assign({
    responsive: true, displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    toImageButtonOptions: { format: "png", scale: 2 },
  }, config));
}

function resetChart(node) {
  if (window.Plotly && node.classList.contains("js-plotly-plot")) Plotly.purge(node);
  return clear(node);
}

function purgeCharts(root) {
  if (!window.Plotly) return;
  $$(".js-plotly-plot", root).forEach((node) => Plotly.purge(node));
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function apiGet(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) value.forEach((v) => query.append(key, v));
    else if (value !== null && value !== undefined && value !== "") query.append(key, value);
  }
  const response = await fetch(`${path}?${query.toString()}`);
  let body;
  try { body = await response.json(); } catch (_) { throw new Error("The server returned an unexpected response."); }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body;
}

function uploadFile(file, { onProgress, onProcessing } = {}) {
  return new Promise((resolve, reject) => {
    const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
    if (!ALLOWED.includes(ext)) return reject(new Error(`"${file.name}" is not a CSV file. Choose a .csv, .tsv or .txt file.`));
    if (file.size === 0) return reject(new Error("The file is empty."));
    if (file.size > MAX_MB * 1024 * 1024) return reject(new Error(`The file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${MAX_MB} MB.`));

    const form = new FormData();
    form.append("file", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.upload.onload = () => { if (onProcessing) onProcessing(); };
    xhr.onerror = () => reject(new Error("Could not reach the DataLens server. Check that python app.py is still running in VS Code."));
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch (_) { /* handled below */ }
      if (xhr.status === 200 && body) resolve(body);
      else reject(new Error((body && body.error) || `Upload failed (status ${xhr.status}).`));
    };
    xhr.send(form);
  });
}

// ---------------------------------------------------------------------------
// Landing page: drag and drop, file picker, samples
// ---------------------------------------------------------------------------
function setupLanding() {
  const zone = $("#dropzone");
  const input = $("#file-input");
  input.addEventListener("change", () => { if (input.files[0]) startUpload(input.files[0]); input.value = ""; });
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("dragging"); }));
  ["dragleave", "dragend"].forEach((type) => zone.addEventListener(type, () => zone.classList.remove("dragging")));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragging");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) startUpload(file);
  });
  // Stop the browser from opening a file dropped outside the zone.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  $$("[data-sample]").forEach((btn) => btn.addEventListener("click", async () => {
    try {
      const res = await fetch(`/samples/${encodeURIComponent(btn.dataset.sample)}`);
      if (!res.ok) throw new Error("Sample file not found.");
      const blob = await res.blob();
      startUpload(new File([blob], btn.dataset.sample, { type: "text/csv" }));
    } catch (err) { showUploadError(err.message); }
  }));
}

function showUploadError(message) {
  $("#upload-status").hidden = true;
  $("#dropzone").classList.remove("busy");
  const box = $("#upload-error");
  box.textContent = message;
  box.hidden = false;
}

async function startUpload(file) {
  $("#upload-error").hidden = true;
  $("#upload-status").hidden = false;
  $("#dropzone").classList.add("busy");
  const bar = $("#progress-bar");
  const msg = $("#upload-message");
  bar.style.width = "0%";
  msg.textContent = `Uploading ${file.name}…`;
  try {
    const report = await uploadFile(file, {
      onProgress: (f) => { bar.style.width = `${Math.round(f * 70)}%`; msg.textContent = `Uploading ${file.name}… ${Math.round(f * 100)}%`; },
      onProcessing: () => { bar.style.width = "85%"; msg.textContent = "Analysing the data…"; },
    });
    bar.style.width = "100%";
    showReport(report);
  } catch (err) {
    showUploadError(err.message);
  }
}

function resetToLanding() {
  clearReport();
  state.report = null; state.id = null;
  $("#report").hidden = true;
  $("#report-actions").hidden = true;
  $("#landing").hidden = false;
  $("#upload-status").hidden = true;
  $("#dropzone").classList.remove("busy");
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
const DYNAMIC_IDS = ["kpis", "load-notes", "preview", "insights", "quality-kpis", "chart-missing", "quality-issues", "columns-table",
  "stats-table", "distribution-grid", "category-grid", "chart-corr", "corr-pairs", "sc-stats", "chart-scatter", "sm-cols", "sm-note",
  "chart-splom", "pv-table", "chart-pivot", "ct-stats", "ct-table", "chart-crosstab", "ts-kpis", "chart-ts", "ts-anomalies",
  "ts-seasonal", "outlier-table", "box-grid", "compare-result", "compare-status",
  "sc-x", "sc-y", "sc-color", "pv-rows", "pv-cols", "pv-values", "ct-a", "ct-b", "ts-date", "ts-value"];

function clearReport() {
  purgeCharts($("#report"));
  DYNAMIC_IDS.forEach((id) => { const node = document.getElementById(id); if (node) clear(node); });
  state.crosstab = null;
  state.corrMethod = "pearson";
  state.ctMode = "counts";
  $$("[data-ctmode]").forEach((x) => x.classList.toggle("active", x.dataset.ctmode === "counts"));
}

function showReport(report) {
  clearReport();
  state.report = report;
  state.id = report.dataset.id;
  $("#landing").hidden = true;
  $("#report").hidden = false;
  $("#report-actions").hidden = false;
  $("#file-chip").textContent = report.dataset.name;
  $("#file-chip").title = report.dataset.name;
  window.scrollTo(0, 0);

  const steps = [renderOverview, renderInsights, renderQuality, renderColumns, renderStats, renderDistributions,
    renderCategories, renderCorrelation, setupScatter, setupMatrix, setupPivot, setupCrosstab, setupTimeseries,
    renderOutliers, setupCompare];
  for (const step of steps) {
    try { step(report); } catch (err) { console.error(step.name, err); }
  }
  markUnavailableSections(report);
}

function markUnavailableSections(r) {
  const unavailable = {
    "#sec-stats": !r.columns.numeric.length, "#sec-distributions": !r.columns.numeric.length,
    "#sec-categories": !Object.keys(r.categories).length, "#sec-correlation": !r.correlation.pearson,
    "#sec-multivariate": r.columns.numeric.length < 2 && !r.columns.groupable.length,
    "#sec-crosstab": r.columns.groupable.length < 2, "#sec-timeseries": !r.columns.datetime.length,
    "#sec-outliers": !r.outliers.length,
  };
  $$(".sidenav a").forEach((a) => a.classList.toggle("unavailable", !!unavailable[a.getAttribute("href")]));
}

function emptyMessage(container, text) { clear(container).append(el("div", { class: "empty" }, text)); }

// ----- Overview -----
function renderOverview(r) {
  const d = r.dataset, load = r.load, t = r.type_counts;
  $("#report-title").textContent = d.name;
  const size = d.size_bytes >= 1048576 ? `${(d.size_bytes / 1048576).toFixed(1)} MB` : `${(d.size_bytes / 1024).toFixed(1)} KB`;
  clear($("#kpis")).append(
    kpi(fmt(d.rows), "rows"), kpi(fmt(d.columns), "columns"),
    kpi(fmt(t.numeric), "numeric columns"), kpi(fmt(t.categorical), "categorical columns"),
    kpi(fmt(t.datetime), "date/time columns"), kpi(size, `file size, analysed in ${d.seconds}s`),
  );
  const notes = clear($("#load-notes"));
  const skipped = [t.identifier ? plural(t.identifier, "ID column") : "", t.text ? plural(t.text, "free-text column") : ""].filter(Boolean);
  notes.append(note(`Read as ${load.encoding} text with ${load.delimiter}-separated values.` +
    (skipped.length ? ` ${skipped.join(" and ")} ${skipped.length === 1 && (t.identifier + t.text) === 1 ? "is" : "are"} profiled but not charted.` : "")));
  load.notes.forEach((n) => notes.append(note(n, "warning")));

  const rows = r.preview.rows;
  clear($("#preview")).append(table(["Row", ...r.preview.columns], rows.map((row, i) => [i + 1, ...row]), { markMissing: true }));
}

// ----- Insights -----
function renderInsights(r) {
  const list = el("ul", { class: "insight-list" });
  r.insights.forEach((i) => list.append(el("li", { class: i.level }, el("div", { class: "insight-area" }, i.area), el("div", {}, i.text))));
  clear($("#insights")).append(list);
}

// ----- Data quality -----
function renderQuality(r) {
  const q = r.quality;
  clear($("#quality-kpis")).append(
    kpi(pct(q.completeness_pct), "of cells filled in", q.completeness_pct >= 95 ? "ok" : q.completeness_pct >= 80 ? "warn" : "bad"),
    kpi(fmt(q.missing_cells), "missing cells", q.missing_cells ? "warn" : "ok"),
    kpi(fmt(q.columns_with_missing), "columns with missing values"),
    kpi(fmt(q.duplicate_rows), `duplicate rows (${pct(q.duplicate_pct)})`, q.duplicate_rows ? "warn" : "ok"),
    kpi(fmt(r.schema.reduce((s, c) => s + c.invalid, 0)), "values that didn't match their column type"),
  );

  const withMissing = q.per_column.filter((c) => c.missing > 0).sort((a, b) => b.missing_pct - a.missing_pct);
  if (withMissing.length) {
    plot("chart-missing", [{
      type: "bar", orientation: "h", x: withMissing.map((c) => c.missing_pct), y: withMissing.map((c) => c.name),
      marker: { color: C.amber }, text: withMissing.map((c) => `${fmt(c.missing)} (${c.missing_pct.toFixed(1)}%)`),
      textposition: "auto", hovertemplate: "%{y}: %{x:.2f}% missing<extra></extra>",
    }], {
      xaxis: { title: { text: "Missing values (%)" }, range: [0, Math.max(5, Math.min(100, withMissing[0].missing_pct * 1.15))] },
      yaxis: { autorange: "reversed" }, height: Math.max(220, 60 + withMissing.length * 30), margin: { l: 150, r: 18, t: 10, b: 48 },
    });
  } else {
    emptyMessage($("#chart-missing"), "No missing values in any column.");
  }

  const issues = clear($("#quality-issues"));
  if (q.duplicate_rows) {
    issues.append(note(`${plural(q.duplicate_rows, "row")} repeat an earlier row exactly (for example data rows ${q.duplicate_examples.slice(0, 6).join(", ")}). Use "Download cleaned CSV" and choose to remove duplicates if they are not intended.`, "warning"));
  }
  if (!q.issues.length && !q.duplicate_rows) {
    issues.append(note("No consistency problems were detected.", "good"));
    return;
  }
  if (q.issues.length) {
    issues.append(table(["Column", "What was found"], q.issues.map((i) => [i.column, i.text]), { wrap: [1] }));
  }
}

// ----- Column profiles -----
function typeTag(type) { return el("span", { class: `type-tag type-${type}` }, type === "datetime" ? "date/time" : type); }

function renderColumns(r) {
  const rows = r.schema.map((c) => [
    c.name, typeTag(c.type), c.dtype_label || "", fmt(c.non_null), fmt(c.missing), pct(c.missing_pct),
    fmt(c.unique), (c.samples || []).join(", "), c.notes.join(" "),
  ]);
  clear($("#columns-table")).append(table(
    ["Column", "Detected type", "Format", "Non-missing", "Missing", "Missing %", "Distinct values", "Example values", "Notes"],
    rows, { numeric: [3, 4, 5, 6], wrap: [8] }));
}

// ----- Summary statistics -----
function renderStats(r) {
  const cols = r.columns.numeric;
  if (!cols.length) return emptyMessage($("#stats-table"), "No numeric columns were detected, so there is nothing to summarise here.");
  const rows = cols.map((c) => {
    const s = r.stats[c];
    return [c, fmt(s.count), fmt(s.missing), fmt(s.mean), fmt(s.median), s.mode === null || s.mode === undefined ? "no repeats" : fmt(s.mode),
      fmt(s.std), fmt(s.variance), fmt(s.min), fmt(s.q1), fmt(s.q3), fmt(s.max), fmt(s.iqr), fmt(s.p5), fmt(s.p95),
      fmt(s.skewness), fmt(s.kurtosis), s.skew_label];
  });
  clear($("#stats-table")).append(table(
    ["Column", "Count", "Missing or invalid", "Mean", "Median", "Mode", "Std dev", "Variance", "Min", "Q1 (25%)", "Q3 (75%)", "Max", "IQR", "5th pct", "95th pct", "Skewness", "Kurtosis", "Shape"],
    rows, { numeric: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] }));
}

// ----- Distributions -----
function renderDistributions(r) {
  const grid = $("#distribution-grid");
  purgeCharts(grid); clear(grid);
  const cols = r.columns.numeric;
  if (!cols.length) return emptyMessage(grid, "No numeric columns to draw histograms for.");
  cols.forEach((c, i) => {
    const h = r.distributions[c].histogram, s = r.stats[c];
    if (!h) return;
    const chartId = `hist-${i}`;
    grid.append(el("div", { class: "chart-card" },
      el("h4", {}, c),
      el("p", { class: "meta" }, `Mean ${fmt(s.mean)}, median ${fmt(s.median)}, ${s.skew_label}`),
      el("div", { class: "chart", id: chartId })));
    const trace = h.kind === "discrete"
      ? { type: "bar", x: h.x, y: h.y, marker: { color: C.accent }, hovertemplate: "%{x}: %{y} rows<extra></extra>" }
      : { type: "bar", x: h.centers, y: h.counts, width: h.width * 0.96, marker: { color: C.accent },
          customdata: h.centers.map((_, k) => [h.edges[k], h.edges[k + 1]]),
          hovertemplate: "%{customdata[0]:.4g} to %{customdata[1]:.4g}: %{y} rows<extra></extra>" };
    const lines = [];
    if (s.mean !== undefined) lines.push({ type: "line", x0: s.mean, x1: s.mean, yref: "paper", y0: 0, y1: 1, line: { color: C.bad, width: 2 } });
    if (s.median !== undefined) lines.push({ type: "line", x0: s.median, x1: s.median, yref: "paper", y0: 0, y1: 1, line: { color: C.ink, width: 2, dash: "dash" } });
    plot(chartId, [trace], { shapes: lines, bargap: 0.04, height: 260, margin: { l: 48, r: 10, t: 8, b: 36 }, yaxis: { title: { text: "Rows" } } });
  });
}

// ----- Categories -----
function renderCategories(r) {
  const grid = $("#category-grid");
  purgeCharts(grid); clear(grid);
  const names = Object.keys(r.categories);
  if (!names.length) return emptyMessage(grid, "No categorical columns were detected.");
  names.forEach((name, i) => {
    const c = r.categories[name];
    const barId = `cat-bar-${i}`, pieId = `cat-pie-${i}`;
    const freq = table(["Value", "Count", "Share"], c.labels.map((l, k) => [l, fmt(c.counts[k]), pct(c.percents[k])]), { numeric: [1, 2] });
    const block = el("div", { class: `cat-block ${c.allow_pie ? "" : "no-pie"}` },
      el("div", {},
        el("h4", {}, name),
        el("p", { class: "meta" }, `${plural(c.unique, "distinct value")}. Most common: "${c.mode}" (${pct(c.mode_pct)}).` + (c.missing ? ` ${fmt(c.missing)} missing.` : "")),
        el("div", { class: "chart", id: barId }),
        el("details", {}, el("summary", {}, "Frequency table"), freq)),
      c.allow_pie ? el("div", {}, el("div", { class: "chart", id: pieId })) : null);
    grid.append(block);
    plot(barId, [{ type: "bar", x: c.labels, y: c.counts, marker: { color: C.good },
      text: c.percents.map((p) => `${p.toFixed(1)}%`), textposition: "auto", hovertemplate: "%{x}: %{y} rows<extra></extra>" }],
      { height: 280, margin: { l: 48, r: 10, t: 8, b: 70 }, xaxis: { type: "category" }, yaxis: { title: { text: "Rows" } } });
    if (c.allow_pie) {
      plot(pieId, [{ type: "pie", labels: c.labels, values: c.counts, hole: 0.45, sort: false, textinfo: "percent",
        hovertemplate: "%{label}: %{value} rows (%{percent})<extra></extra>", marker: { colors: PALETTE } }],
        { height: 280, showlegend: true, legend: { orientation: "h", y: -0.1 }, margin: { l: 10, r: 10, t: 8, b: 10 } });
    }
  });
}

// ----- Correlation -----
function renderCorrelation(r) {
  $$("[data-method]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.method === state.corrMethod);
    btn.onclick = () => { state.corrMethod = btn.dataset.method; renderCorrelation(state.report); };
  });
  const corr = r.correlation[state.corrMethod];
  const chart = $("#chart-corr");
  if (!corr) {
    resetChart(chart);
    emptyMessage(chart, "Correlation needs at least two numeric columns with varying values.");
    clear($("#corr-pairs"));
    return;
  }
  resetChart(chart);
  const n = corr.columns.length;
  const text = corr.matrix.map((row) => row.map((v) => (v === null ? "" : v.toFixed(2))));
  plot(chart, [{
    type: "heatmap", z: corr.matrix, x: corr.columns, y: corr.columns, zmin: -1, zmax: 1,
    colorscale: [[0, C.bad], [0.5, "#F6F8F7"], [1, C.accent]], text,
    texttemplate: n <= 14 ? "%{text}" : "", hovertemplate: "%{y} vs %{x}: %{z:.3f}<extra></extra>",
    colorbar: { thickness: 12, title: { text: "r" } },
  }], { height: Math.max(420, 110 + n * 38), margin: { l: 130, r: 20, t: 10, b: 120 },
    xaxis: { tickangle: -40, type: "category" }, yaxis: { autorange: "reversed", type: "category" } });

  const pairs = corr.pairs.slice(0, 15);
  clear($("#corr-pairs")).append(
    corr.truncated ? note(`Only the ${n} most complete numeric columns are included.`) : "",
    table(["Column A", "Column B", "r", "Strength", "Rows used"],
      pairs.map((p) => [p.a, p.b, p.r.toFixed(3), p.strength, fmt(p.n)]),
      { numeric: [2, 4], onRowClick: (i) => openScatter(pairs[i].a, pairs[i].b) }));
}

function openScatter(x, y) {
  $("#sc-x").value = x; $("#sc-y").value = y; $("#sc-color").value = "";
  runScatter();
  document.getElementById("sec-multivariate").scrollIntoView({ behavior: "smooth" });
}

// ----- Scatter explorer -----
function setupScatter(r) {
  const nums = r.columns.numeric;
  if (nums.length < 2) {
    emptyMessage($("#chart-scatter"), "Scatter plots need at least two numeric columns.");
    $("#sc-run").disabled = true;
    return;
  }
  $("#sc-run").disabled = false;
  const best = r.correlation.pearson && r.correlation.pearson.pairs[0];
  fillSelect($("#sc-x"), nums, { selected: best ? best.a : nums[0] });
  fillSelect($("#sc-y"), nums, { selected: best ? best.b : nums[1] });
  fillSelect($("#sc-color"), r.columns.groupable, { blank: "None" });
  $("#sc-run").onclick = runScatter;
  runScatter();
}

async function runScatter() {
  const chart = $("#chart-scatter"), strip = $("#sc-stats");
  const x = $("#sc-x").value, y = $("#sc-y").value, color = $("#sc-color").value;
  clear(strip).append(el("span", { class: "loading" }, "Calculating…"));
  try {
    const s = await apiGet(`/api/datasets/${state.id}/scatter`, { x, y, color });
    clear(strip).append(
      el("span", {}, "Pearson r ", el("b", {}, fmt(s.pearson, 3))),
      el("span", {}, "Spearman ρ ", el("b", {}, fmt(s.spearman, 3))),
      el("span", {}, "R² ", el("b", {}, fmt(s.r_squared, 3))),
      el("span", {}, "Trend line ", el("b", {}, s.slope === null ? "—" : `y = ${fmt(s.slope, 4)}x ${s.intercept >= 0 ? "+" : "−"} ${fmt(Math.abs(s.intercept), 4)}`)),
      s.p_value !== null ? el("span", {}, "p-value ", el("b", {}, s.p_value < 0.001 ? "< 0.001" : s.p_value.toFixed(3))) : "",
      el("span", {}, el("b", {}, s.strength)),
      el("span", {}, `${fmt(s.n)} rows` + (s.sampled ? ` (${fmt(s.shown)} random points drawn)` : "")),
    );
    const traces = s.groups.map((g, i) => ({
      type: s.n > 1500 ? "scattergl" : "scatter", mode: "markers", name: g.name, x: g.x, y: g.y,
      marker: { size: 6, opacity: 0.65, color: s.color ? PALETTE[i % PALETTE.length] : C.accent },
      hovertemplate: `${x}: %{x}<br>${y}: %{y}<extra>${s.color ? g.name : ""}</extra>`,
    }));
    if (s.trend) traces.push({ type: "scatter", mode: "lines", name: "Linear trend", x: s.trend.x, y: s.trend.y, line: { color: C.bad, width: 2 }, hoverinfo: "skip" });
    resetChart(chart);
    plot(chart, traces, { height: 460, showlegend: !!s.color || !!s.trend, legend: { orientation: "h", y: -0.18 },
      xaxis: { title: { text: x } }, yaxis: { title: { text: y } } });
  } catch (err) {
    clear(strip).append(el("span", { class: "error-text" }, err.message));
  }
}

// ----- Scatter matrix -----
function setupMatrix(r) {
  const nums = r.columns.numeric;
  const box = clear($("#sm-cols"));
  if (nums.length < 2) {
    emptyMessage($("#chart-splom"), "A scatter matrix needs at least two numeric columns.");
    $("#sm-run").disabled = true;
    return;
  }
  $("#sm-run").disabled = false;
  // Default: the columns involved in the strongest correlations.
  const pairs = r.correlation.pearson ? r.correlation.pearson.pairs : [];
  const picked = [];
  pairs.forEach((p) => [p.a, p.b].forEach((c) => { if (!picked.includes(c) && picked.length < 4) picked.push(c); }));
  nums.forEach((c) => { if (picked.length < 2 && !picked.includes(c)) picked.push(c); });
  nums.forEach((c) => box.append(el("label", {}, el("input", { type: "checkbox", value: c, checked: picked.includes(c) ? true : null }), c)));
  $("#sm-run").onclick = runMatrix;
  runMatrix();
}

async function runMatrix() {
  const cols = $$("#sm-cols input:checked").map((i) => i.value);
  const chart = $("#chart-splom"), noteEl = $("#sm-note");
  if (cols.length < 2 || cols.length > 6) { noteEl.textContent = "Select between 2 and 6 columns."; return; }
  noteEl.textContent = "Drawing…";
  try {
    const m = await apiGet(`/api/datasets/${state.id}/scatter-matrix`, { cols });
    noteEl.textContent = `${fmt(m.n)} rows have values in all selected columns` + (m.sampled ? `; ${fmt(m.shown)} random rows are drawn.` : ".");
    resetChart(chart);
    const axes = {};
    cols.forEach((_, i) => {
      const suffix = i === 0 ? "" : i + 1;
      axes[`xaxis${suffix}`] = { gridcolor: C.grid, zeroline: false, tickfont: { size: 10 } };
      axes[`yaxis${suffix}`] = { gridcolor: C.grid, zeroline: false, tickfont: { size: 10 } };
    });
    plot(chart, [{ type: "splom", dimensions: m.dimensions, showupperhalf: false, diagonal: { visible: false },
      marker: { size: 4, color: C.accent, opacity: 0.55 } }],
    Object.assign({ height: Math.max(420, cols.length * 150), margin: { l: 70, r: 20, t: 10, b: 60 }, dragmode: "select" }, axes));
  } catch (err) { noteEl.textContent = err.message; }
}

// ----- Pivot table -----
function setupPivot(r) {
  const groups = r.columns.groupable;
  if (!groups.length) {
    emptyMessage($("#pv-table"), "Pivot tables need at least one categorical column.");
    $("#pv-run").disabled = true;
    return;
  }
  $("#pv-run").disabled = false;
  fillSelect($("#pv-rows"), groups, { selected: groups[0] });
  fillSelect($("#pv-cols"), groups, { blank: "None" });
  fillSelect($("#pv-values"), r.columns.numeric, { blank: "Row count" });
  const firstContinuous = r.columns.numeric.find((c) => !groups.includes(c));
  if (firstContinuous) $("#pv-values").value = firstContinuous;
  $("#pv-agg").value = firstContinuous ? "mean" : "count";
  $("#pv-run").onclick = runPivot;
  runPivot();
}

async function runPivot() {
  const box = $("#pv-table"), chart = $("#chart-pivot");
  const rows = $("#pv-rows").value, cols = $("#pv-cols").value, values = $("#pv-values").value;
  const agg = values ? $("#pv-agg").value : "count";
  clear(box).append(el("p", { class: "loading" }, "Building…"));
  try {
    const p = await apiGet(`/api/datasets/${state.id}/pivot`, { rows, cols, values, agg });
    const aggName = { mean: "Average", sum: "Sum", median: "Median", min: "Minimum", max: "Maximum", count: "Count" }[p.agg];
    const title = p.agg === "count" ? "Row count" : `${aggName} of ${p.values}`;
    clear(box).append(el("p", { class: "hint" }, `${title} by ${p.rows}${p.cols ? ` and ${p.cols}` : ""}.`));
    resetChart(chart);
    if (p.cols) {
      box.append(table([`${p.rows} \\ ${p.cols}`, ...p.col_labels], p.row_labels.map((l, i) => [l, ...p.matrix[i].map((v) => fmt(v))]),
        { numeric: p.col_labels.map((_, i) => i + 1) }));
      plot(chart, [{ type: "heatmap", z: p.matrix, x: p.col_labels, y: p.row_labels, colorscale: [[0, "#F6F8F7"], [1, C.accent]],
        hovertemplate: `${p.rows}: %{y}<br>${p.cols}: %{x}<br>${title}: %{z:.4g}<extra></extra>`, colorbar: { thickness: 12 } }],
      { height: Math.max(300, 90 + p.row_labels.length * 30), margin: { l: 130, r: 20, t: 10, b: 80 },
        xaxis: { type: "category" }, yaxis: { type: "category", autorange: "reversed" } });
    } else {
      box.append(table([p.rows, title, "Rows in group"], p.row_labels.map((l, i) => [l, fmt(p.matrix[i][0]), fmt(p.counts[i][0])]), { numeric: [1, 2] }));
      plot(chart, [{ type: "bar", x: p.row_labels, y: p.matrix.map((r) => r[0]), marker: { color: C.accent },
        hovertemplate: `%{x}: %{y:.4g}<extra></extra>` }],
      { height: 320, xaxis: { type: "category" }, yaxis: { title: { text: title } }, margin: { l: 60, r: 10, t: 10, b: 80 } });
    }
  } catch (err) { clear(box).append(el("p", { class: "error-text" }, err.message)); }
}

// ----- Cross-tabulation -----
function setupCrosstab(r) {
  const groups = r.columns.groupable;
  if (groups.length < 2) {
    emptyMessage($("#ct-table"), "Cross-tabulation needs at least two categorical columns.");
    $("#ct-run").disabled = true;
    return;
  }
  $("#ct-run").disabled = false;
  const nonNumeric = groups.filter((g) => !r.columns.numeric.includes(g));
  const a = nonNumeric[0] || groups[0];
  const b = (nonNumeric[1] && nonNumeric[1] !== a) ? nonNumeric[1] : groups.find((g) => g !== a);
  fillSelect($("#ct-a"), groups, { selected: a });
  fillSelect($("#ct-b"), groups, { selected: b });
  $("#ct-run").onclick = runCrosstab;
  $$("[data-ctmode]").forEach((btn) => btn.onclick = () => {
    state.ctMode = btn.dataset.ctmode;
    $$("[data-ctmode]").forEach((x) => x.classList.toggle("active", x === btn));
    if (state.crosstab) drawCrosstab(state.crosstab);
  });
  runCrosstab();
}

async function runCrosstab() {
  const box = $("#ct-table"), strip = $("#ct-stats");
  clear(strip); clear(box).append(el("p", { class: "loading" }, "Building…"));
  try {
    state.crosstab = await apiGet(`/api/datasets/${state.id}/crosstab`, { a: $("#ct-a").value, b: $("#ct-b").value });
    drawCrosstab(state.crosstab);
  } catch (err) { clear(box).append(el("p", { class: "error-text" }, err.message)); }
}

function drawCrosstab(ct) {
  const box = clear($("#ct-table")), strip = clear($("#ct-stats")), chart = $("#chart-crosstab");
  const showPct = state.ctMode === "pct";
  if (ct.chi2 !== null) {
    const v = ct.cramers_v;
    const vText = v < 0.1 ? "negligible" : v < 0.3 ? "weak" : v < 0.5 ? "moderate" : "strong";
    strip.append(
      el("span", {}, "Chi-square ", el("b", {}, fmt(ct.chi2, 3))),
      el("span", {}, "Degrees of freedom ", el("b", {}, ct.dof)),
      ct.p_value !== null ? el("span", {}, "p-value ", el("b", {}, ct.p_value < 0.001 ? "< 0.001" : ct.p_value.toFixed(4))) : "",
      el("span", {}, "Cramér's V ", el("b", {}, `${fmt(v, 3)} (${vText})`)),
      el("span", {}, `${fmt(ct.n)} rows`),
    );
    if (ct.p_value !== null) {
      box.append(note(ct.p_value < 0.05
        ? `p < 0.05: the distribution of ${ct.b} differs across ${ct.a} groups more than chance alone would explain.`
        : `p ≥ 0.05: no evidence that ${ct.a} and ${ct.b} are related in this data.`, ct.p_value < 0.05 ? "info" : "good"));
    }
    if (ct.low_expected_pct > 20) box.append(note(`${ct.low_expected_pct.toFixed(0)}% of cells have an expected count below 5, so the chi-square result is less reliable.`, "warning"));
  }
  const header = [`${ct.a} \\ ${ct.b}`, ...ct.col_labels, showPct ? "" : "Total"].filter((h) => h !== "");
  const rows = ct.row_labels.map((l, i) => {
    const cells = showPct ? ct.row_pct[i].map((v) => `${v.toFixed(1)}%`) : ct.counts[i].map((v) => fmt(v));
    return showPct ? [l, ...cells] : [l, ...cells, fmt(ct.row_totals[i])];
  });
  if (!showPct) rows.push(["Total", ...ct.col_totals.map((v) => fmt(v)), fmt(ct.n)]);
  box.append(table(header, rows, { numeric: header.map((_, i) => i).slice(1) }));

  resetChart(chart);
  const traces = ct.col_labels.map((colLabel, j) => ({
    type: "bar", name: colLabel, x: ct.row_labels,
    y: ct.row_labels.map((_, i) => (showPct ? ct.row_pct[i][j] : ct.counts[i][j])),
    marker: { color: PALETTE[j % PALETTE.length] },
    hovertemplate: `${ct.a}: %{x}<br>${ct.b}: ${colLabel}<br>${showPct ? "%{y:.1f}%" : "%{y} rows"}<extra></extra>`,
  }));
  plot(chart, traces, { barmode: "stack", showlegend: true, legend: { orientation: "h", y: -0.25, title: { text: ct.b } }, height: 380,
    xaxis: { type: "category" }, yaxis: { title: { text: showPct ? "Share of row (%)" : "Rows" } }, margin: { l: 60, r: 10, t: 10, b: 80 } });
}

// ----- Time series -----
function setupTimeseries(r) {
  const dates = r.columns.datetime;
  if (!dates.length) {
    $("#ts-body").hidden = true;
    const e = $("#ts-empty");
    e.hidden = false;
    e.textContent = "No date or time column was detected in this file, so time-series analysis is not available. Dates such as 2024-03-15, 15/03/2024 or Mar 2024 are recognised automatically.";
    return;
  }
  $("#ts-body").hidden = false; $("#ts-empty").hidden = true;
  const ts = r.timeseries;
  fillSelect($("#ts-date"), dates, { selected: ts ? ts.date : dates[0] });
  fillSelect($("#ts-value"), r.columns.numeric, { blank: "Number of records", selected: ts && ts.value ? ts.value : null });
  if (ts) { $("#ts-agg").value = ts.agg; $("#ts-freq").value = "auto"; }
  $("#ts-value").onchange = () => { if (!$("#ts-value").value) $("#ts-agg").value = "count"; else if ($("#ts-agg").value === "count") $("#ts-agg").value = "sum"; };
  $("#ts-run").onclick = runTimeseries;
  if (ts) drawTimeseries(ts);
  else if (r.timeseries_error) emptyMessage($("#chart-ts"), r.timeseries_error);
}

async function runTimeseries() {
  const chart = $("#chart-ts");
  clear($("#ts-kpis")).append(el("p", { class: "loading" }, "Resampling…"));
  try {
    const value = $("#ts-value").value;
    const ts = await apiGet(`/api/datasets/${state.id}/timeseries`, {
      date: $("#ts-date").value, value, agg: value ? $("#ts-agg").value : "count", freq: $("#ts-freq").value,
    });
    drawTimeseries(ts);
  } catch (err) {
    clear($("#ts-kpis")).append(el("p", { class: "error-text" }, err.message));
    resetChart(chart);
  }
}

function drawTimeseries(ts) {
  const s = ts.summary;
  const aggWord = { sum: "Total", mean: "Average", median: "Median", min: "Minimum", max: "Maximum", count: "Count" }[ts.agg];
  const measure = ts.agg === "count" ? (ts.value ? `Count of ${ts.value}` : "Number of records") : `${aggWord} ${ts.value}`;
  const trendTone = s.trend === "increasing" ? "ok" : s.trend === "decreasing" ? "bad" : "";
  clear($("#ts-kpis")).append(
    kpi(ts.freq_label, `periods (${fmt(s.periods)} of them)`),
    kpi(s.trend || "—", "overall trend", trendTone),
    kpi(fmt(s.peak_value), `highest, period from ${dateOnly(s.peak_period)}`),
    kpi(fmt(s.low_value), `lowest, period from ${dateOnly(s.low_period)}`),
    kpi(s.first_to_last_pct === null || s.first_to_last_pct === undefined ? "—" : `${s.first_to_last_pct > 0 ? "+" : ""}${s.first_to_last_pct.toFixed(1)}%`, "first period to last period"),
    kpi(fmt(s.empty_periods), "periods with no records", s.empty_periods ? "warn" : ""),
  );
  const chart = $("#chart-ts");
  resetChart(chart);
  const traces = [
    { type: "scatter", mode: ts.x.length > 60 ? "lines" : "lines+markers", name: measure, x: ts.x, y: ts.y,
      line: { color: C.accent, width: 1.6 }, marker: { size: 5 }, connectgaps: false,
      hovertemplate: "%{x|%d %b %Y}: %{y:,.4g}<extra></extra>" },
    { type: "scatter", mode: "lines", name: ts.ma_label, x: ts.x, y: ts.ma, line: { color: C.amber, width: 2.5 },
      hovertemplate: "%{x|%d %b %Y}: %{y:,.4g}<extra>moving average</extra>" },
  ];
  if (ts.anomalies.length) {
    traces.push({ type: "scatter", mode: "markers", name: "Unusual period", x: ts.anomalies.map((a) => a.period), y: ts.anomalies.map((a) => a.value),
      marker: { color: C.bad, size: 10, symbol: "circle-open", line: { width: 2.5 } },
      hovertemplate: "%{x|%d %b %Y}: %{y:,.4g}<extra>unusual</extra>" });
  }
  plot(chart, traces, { height: 460, showlegend: true, legend: { orientation: "h", y: -0.18 },
    xaxis: { type: "date", title: { text: `${ts.date} (${ts.freq_label.toLowerCase()})` }, rangeslider: { visible: ts.x.length > 40, thickness: 0.06 } },
    yaxis: { title: { text: measure } } });

  const an = clear($("#ts-anomalies"));
  if (ts.anomalies.length) {
    an.append(el("h3", {}, "Unusual periods"),
      el("p", { class: "hint" }, "Periods far from the local median of their neighbours (robust Z-score above 3.5)."),
      table(["Period starting", "Value", "Typical nearby", "Direction"],
        ts.anomalies.map((a) => [dateOnly(a.period), fmt(a.value), fmt(a.expected), a.direction]), { numeric: [1, 2] }));
  }
  const notes = [];
  if (s.missing_dates) notes.push(`${fmt(s.missing_dates)} rows had no valid date and were left out.`);
  if (s.missing_values) notes.push(`${fmt(s.missing_values)} rows had no value for ${ts.value} and were left out.`);
  notes.forEach((n) => an.append(note(n, "warning")));

  const grid = $("#ts-seasonal");
  purgeCharts(grid); clear(grid);
  const blocks = [["month", "By calendar month"], ["weekday", "By day of week"], ["hour", "By hour of day"]];
  let any = false;
  blocks.forEach(([key, title]) => {
    const b = ts.seasonal[key];
    if (!b) return;
    any = true;
    const id = `season-${key}`;
    grid.append(el("div", { class: "chart-card" }, el("h4", {}, title), el("p", { class: "meta" }, `${b.description}. Highest: ${b.peak}.`), el("div", { class: "chart", id })));
    plot(id, [{ type: "bar", x: b.labels, y: b.values, marker: { color: b.labels.map((l) => (l === b.peak ? C.amber : C.accent)) },
      hovertemplate: "%{x}: %{y:,.4g}<extra></extra>" }], { height: 260, xaxis: { type: "category" }, margin: { l: 56, r: 10, t: 8, b: 40 } });
  });
  if (!any) emptyMessage(grid, "Seasonal patterns need at least 12 months of data (by month), 14 days covering every weekday (by weekday), or times of day (by hour).");
}

// ----- Outliers -----
function renderOutliers(r) {
  const grid = $("#box-grid");
  purgeCharts(grid); clear(grid);
  if (!r.outliers.length) {
    emptyMessage($("#outlier-table"), "Outlier detection needs numeric columns with at least 4 values.");
    return;
  }
  const maxPct = Math.max(1, ...r.outliers.map((o) => o.iqr_pct));
  const bar = (o) => el("div", { class: "bar-cell" }, el("span", { class: "bar", style: `width:${Math.max(2, (o.iqr_pct / maxPct) * 90)}px` }), `${fmt(o.iqr_count)} (${pct(o.iqr_pct)})`);
  clear($("#outlier-table")).append(table(
    ["Column", "IQR outliers", "Lower fence", "Upper fence", "Z-score outliers (|z| > 3)", "Flagged by both", "Most extreme values (data row)"],
    r.outliers.map((o) => [o.column, bar(o), fmt(o.lower_bound), fmt(o.upper_bound), `${fmt(o.z_count)} (${pct(o.z_pct)})`, fmt(o.both_count),
      o.extremes.length ? o.extremes.map((e) => `${fmt(e.value)} (row ${e.row})`).join(", ") : "none"]),
    { numeric: [2, 3, 5], wrap: [6] }));

  r.columns.numeric.forEach((c, i) => {
    const b = r.distributions[c].box;
    if (!b) return;
    const id = `box-${i}`;
    grid.append(el("div", { class: "chart-card" }, el("h4", {}, c),
      el("p", { class: "meta" }, `${plural(b.outlier_count, "IQR outlier")}. Median ${fmt(b.median)}, IQR ${fmt(b.q3 - b.q1)}.`),
      el("div", { class: "chart", id })));
    const traces = [{ type: "box", name: c, x: [c], q1: [b.q1], median: [b.median], q3: [b.q3], mean: [b.mean],
      lowerfence: [b.lowerfence], upperfence: [b.upperfence], boxpoints: false,
      marker: { color: C.accent }, line: { color: C.accent }, fillcolor: "rgba(31,110,140,0.18)", hoverinfo: "y" }];
    if (b.outliers.length) {
      traces.push({ type: "scatter", mode: "markers", x: b.outliers.map(() => c), y: b.outliers, name: "Outliers",
        marker: { color: C.bad, size: 6, opacity: 0.7 }, hovertemplate: "%{y:,.4g}<extra>outlier</extra>" });
    }
    plot(id, traces, { height: 260, xaxis: { type: "category", showticklabels: false }, margin: { l: 56, r: 10, t: 8, b: 20 } });
  });
}

// ----- Compare datasets -----
function setupCompare() {
  const input = $("#compare-input");
  input.onchange = async () => {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    const status = $("#compare-status");
    status.textContent = `Uploading ${file.name}…`;
    try {
      const other = await uploadFile(file, { onProgress: (f) => { status.textContent = `Uploading ${file.name}… ${Math.round(f * 100)}%`; }, onProcessing: () => { status.textContent = "Analysing…"; } });
      const cmp = await apiGet("/api/compare", { a: state.id, b: other.dataset.id });
      status.textContent = "";
      drawCompare(cmp);
    } catch (err) { status.textContent = err.message; }
  };
  $("#compare-label").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
}

function drawCompare(cmp) {
  const box = $("#compare-result");
  purgeCharts(box); clear(box);
  box.append(table(["", "Rows", "Columns", "Missing cells", "Duplicate rows"], [
    [`A: ${cmp.a.name}`, fmt(cmp.a.rows), fmt(cmp.a.columns), pct(cmp.a.missing_pct), fmt(cmp.a.duplicates)],
    [`B: ${cmp.b.name}`, fmt(cmp.b.rows), fmt(cmp.b.columns), pct(cmp.b.missing_pct), fmt(cmp.b.duplicates)],
  ], { numeric: [1, 2, 3, 4] }));
  if (!cmp.common.length) { box.append(note("The two files have no column names in common, so they can't be compared column by column.", "warning")); return; }
  if (cmp.only_a.length) box.append(note(`Only in A: ${cmp.only_a.join(", ")}`, "warning"));
  if (cmp.only_b.length) box.append(note(`Only in B: ${cmp.only_b.join(", ")}`, "warning"));
  cmp.type_mismatch.forEach((m) => box.append(note(`${m.column} is ${m.type_a} in A but ${m.type_b} in B.`, "warning")));

  if (cmp.numeric.length) {
    box.append(el("h3", {}, "Numeric columns"));
    box.append(table(["Column", "Mean A", "Mean B", "Change in mean", "Median A", "Median B", "Std dev A", "Std dev B", "Missing A", "Missing B"],
      cmp.numeric.map((n) => [n.column, fmt(n.mean_a), fmt(n.mean_b), n.mean_change_pct === null ? "—" : `${n.mean_change_pct > 0 ? "+" : ""}${n.mean_change_pct.toFixed(1)}%`,
        fmt(n.median_a), fmt(n.median_b), fmt(n.std_a), fmt(n.std_b), pct(n.missing_pct_a), pct(n.missing_pct_b)]),
      { numeric: [1, 2, 3, 4, 5, 6, 7, 8, 9] }));
    const withChange = cmp.numeric.filter((n) => n.mean_change_pct !== null);
    if (withChange.length) {
      const chart = el("div", { class: "chart", id: "chart-compare" });
      box.append(chart);
      plot(chart, [{ type: "bar", orientation: "h", y: withChange.map((n) => n.column), x: withChange.map((n) => n.mean_change_pct),
        marker: { color: withChange.map((n) => (n.mean_change_pct >= 0 ? C.accent : C.bad)) },
        hovertemplate: "%{y}: %{x:+.1f}%<extra></extra>" }],
      { height: Math.max(220, 70 + withChange.length * 32), xaxis: { title: { text: "Change in mean from A to B (%)" }, zeroline: true, zerolinecolor: C.muted },
        yaxis: { autorange: "reversed" }, margin: { l: 150, r: 20, t: 10, b: 48 } });
    }
  }
  if (cmp.categorical.length) {
    box.append(el("h3", {}, "Categorical columns"));
    box.append(table(["Column", "Distinct A", "Distinct B", "Most common A", "Most common B", "New values in B", "Values missing from B"],
      cmp.categorical.map((c) => [c.column, fmt(c.unique_a), fmt(c.unique_b), `${c.top_a} (${pct(c.top_a_pct)})`, `${c.top_b} (${pct(c.top_b_pct)})`,
        c.new_count ? `${c.new_count}: ${c.new_in_b.join(", ")}` : "none", c.missing_count ? `${c.missing_count}: ${c.missing_in_b.join(", ")}` : "none"]),
      { numeric: [1, 2], wrap: [5, 6] }));
  }
}

// ---------------------------------------------------------------------------
// Top bar actions and section highlighting
// ---------------------------------------------------------------------------
function setupTopbar() {
  $("#btn-new").addEventListener("click", resetToLanding);
  $("#btn-print").addEventListener("click", () => window.print());
  $("#btn-download").addEventListener("click", () => {
    if (!state.id) return;
    const dupes = state.report.quality.duplicate_rows;
    let dedupe = false;
    if (dupes) dedupe = window.confirm(`This file has ${dupes} duplicate row(s). Remove them from the downloaded file?\n\nOK = remove duplicates, Cancel = keep all rows.`);
    window.location.href = `/api/datasets/${state.id}/download?dedupe=${dedupe ? 1 : 0}`;
    toast("The cleaned CSV has trimmed spaces, standard missing values and parsed numbers and dates.");
  });
}

function setupNavHighlight() {
  const links = $$(".sidenav a");
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        links.forEach((a) => a.classList.toggle("current", a.getAttribute("href") === `#${entry.target.id}`));
      }
    });
  }, { rootMargin: "-80px 0px -65% 0px" });
  $$(".report .section").forEach((s) => observer.observe(s));
}

document.addEventListener("DOMContentLoaded", () => {
  if (!window.Plotly) $("#plotly-missing").hidden = false;
  setupLanding();
  setupTopbar();
  setupNavHighlight();
});
