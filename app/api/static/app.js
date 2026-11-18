// MatchLens Control Center: no framework, no build. Reads /api/*, refreshes every 5 s, two actions: Play and Stop.
"use strict";

const ICONS = ["video", "send", "topology-star-3", "bolt", "broadcast", "bucket", "database", "database-star",
  "chart-bar", "route", "checklist", "heart-rate-monitor", "box", "download", "player-play", "player-stop",
  "info-circle", "alert-triangle", "stack-2"];
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === "class" ? (e.className = v) : e.setAttribute(k, v);
  for (const k of kids) e.append(k);
  return e;
};
const icon = (name) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "ico");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#i-${name}`);
  s.append(u);
  return s;
};
const spinner = () => $("#spinner").content.cloneNode(true);

async function api(path, options) {
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}

// Tabler icons (MIT, vendored) become <symbol>s inside the diagram: the page and the exported files use the same ones.
async function loadIcons() {
  const defs = $("#icon-defs");
  await Promise.all(ICONS.map(async (name) => {
    const text = await (await fetch(`/static/icons/${name}.svg`)).text();
    const svg = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
    const sym = document.createElementNS("http://www.w3.org/2000/svg", "symbol");
    sym.id = `i-${name}`;
    sym.setAttribute("viewBox", "0 0 24 24");
    for (const a of ["fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"]) sym.setAttribute(a, svg.getAttribute(a));
    sym.innerHTML = svg.innerHTML;
    defs.append(sym);
  }));
}

// ---------------------------------------------------------------- status: lights, warnings, moving arrows, replays
async function refreshStatus() {
  let s;
  try { s = await api("/api/status"); } catch (e) { showWarnings([`The Control Center cannot read the platform: ${e.message}`]); return; }
  for (const [key, light] of Object.entries(s.lights)) {
    const dot = document.querySelector(`.box[data-key="${key}"] .light`);
    if (dot) dot.setAttribute("class", `light ${light}`);
  }
  const arch = $("#arch");
  arch.classList.toggle("moving", s.live_moving);
  arch.classList.toggle("moving-stored", s.stored_moving);
  showWarnings(s.warnings);
  renderReplays(s.replays, s.pipeline_runs);
}

function showWarnings(list) {
  const box = $("#warnings");
  box.replaceChildren(...list.map((w) => el("p", {}, icon("alert-triangle"), w)));
  box.hidden = list.length === 0;
}

function renderReplays(plays, runs) {
  const out = $("#replays");
  out.replaceChildren(...plays.map((p) => {
    const run = runs.find((r) => r.replay_id === p.replay_id);
    const state = p.running ? `playing at x${p.speed}` : p.finished ? (run ? `final whistle: Dagster is building the match (${run.step || run.status.toLowerCase()})` : "final whistle")
      : "stopped";
    const card = el("div", { class: `replay${p.running ? "" : " done"}` },
      el("div", { class: "row" },
        el("strong", {}, p.label),
        el("span", { class: "clock", "aria-label": "football clock" }, p.progress ? p.progress.clock : "–"),
        el("span", {}, state),
        el("span", {}, `${Math.round(p.messages_per_s)} messages/s`)),
      el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
        "aria-valuenow": String(Math.round(100 * (p.progress ? p.progress.share : 0))) },
        el("i", { style: `width:${100 * (p.progress ? p.progress.share : 0)}%` })),
      el("div", { class: "row" }, el("span", { class: "id" }, `replay_id ${p.replay_id}`),
        el("a", { class: "open", href: p.live_url, target: "_blank", rel: "noopener" }, "Open Live page ↗")));
    if (p.running) {
      const stop = el("button", { class: "stop", type: "button" }, icon("player-stop"), "Stop");
      stop.addEventListener("click", async () => {
        stop.disabled = true;
        try { await api("/api/replay/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ match: p.match_id }) }); }
        catch (e) { showError(e.message); }
        refreshStatus();
      });
      card.querySelector(".row").append(stop);
    }
    return card;
  }));
}

// ---------------------------------------------------------------- play
async function loadMatches() {
  const matches = await api("/api/matches");
  $("#match").replaceChildren(...matches.map((m) => el("option", { value: m.match_id, "data-goal": m.first_goal || "" },
    `${m.label}${m.prepared ? "" : " (not prepared)"}`)));
  const syncGoal = () => {
    const goal = $("#match").selectedOptions[0]?.dataset.goal;
    $("#goal-label").textContent = goal ? `30 s before the first goal (${goal})` : "30 s before the first goal";
  };
  $("#match").addEventListener("change", syncGoal);
  syncGoal();
}

function showError(text) {
  const p = $("#play-error");
  p.textContent = text;
  p.hidden = !text;
}

$("#clock").addEventListener("focus", () => { document.querySelector('input[name="start"][value="clock"]').checked = true; });
$("#play-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  showError("");
  const start = new FormData(ev.target).get("start");
  const body = { match: $("#match").value, speed: Number(new FormData(ev.target).get("speed")),
    start: start === "clock" ? $("#clock").value : start };
  const btn = $("#play-btn");
  btn.disabled = true;
  try { await api("/api/replay/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch (e) { showError(e.message); }
  btn.disabled = false;
  refreshStatus();
});

// ---------------------------------------------------------------- popups: a box, the containers
const popup = $("#popup");
let popupTimer = null;
popup.addEventListener("close", () => clearInterval(popupTimer));

async function openBox(key) {
  const body = $("#popup-body");
  body.replaceChildren(spinner());
  popup.showModal();
  const draw = async () => {
    const b = await api(`/api/box/${key}`);
    body.replaceChildren(
      el("h2", { id: "popup-title" }, b.title),
      el("p", { class: "role" }, b.role),
      el("div", { class: "nums" }, ...b.numbers.map((n) => el("div", { class: "tile" }, el("div", { class: "v" }, n.value), el("div", { class: "l" }, n.label)))),
      el("div", { class: "links" }, ...b.links.map((l) => el("a", { href: l.url, target: "_blank", rel: "noopener" }, `${l.label} ↗`))));
  };
  try { await draw(); popupTimer = setInterval(() => draw().catch(() => {}), 5000); }
  catch (e) { body.replaceChildren(el("p", { class: "error" }, e.message)); }
}

async function openContainers() {
  const body = $("#popup-body");
  body.replaceChildren(spinner());
  popup.showModal();
  const draw = async () => {
    const rows = await api("/api/containers");
    const fmt = (v, d = 0) => (v === null || v === undefined ? "–" : v.toFixed(d));
    const up = (s) => (s === null ? "–" : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
    body.replaceChildren(
      el("h2", { id: "popup-title" }, icon("box"), "Containers"),
      el("p", { class: "role" }, `${rows.filter((r) => r.running).length} running. Read from cAdvisor through Prometheus (no Docker socket), refreshed every 5 s.`),
      el("table", { class: "ct" },
        el("thead", {}, el("tr", {}, el("th", {}, "container"), el("th", { class: "num" }, "CPU (cores)"),
          el("th", { class: "num" }, "memory (MiB)"), el("th", { class: "num" }, "limit (MiB)"), el("th", { class: "num" }, "up for"))),
        el("tbody", {}, ...rows.map((r) => el("tr", {},
          el("td", {}, el("span", { class: `dot ${r.running ? "on" : "off"}` }), r.name, r.running ? "" : " (not running)"),
          el("td", { class: "num" }, fmt(r.cpu_cores, 2)), el("td", { class: "num" }, fmt(r.memory_mib)),
          el("td", { class: "num" }, fmt(r.limit_mib)), el("td", { class: "num" }, up(r.uptime_s)))))));
  };
  try { await draw(); popupTimer = setInterval(() => draw().catch(() => {}), 5000); }
  catch (e) { body.replaceChildren(el("p", { class: "error" }, e.message)); }
}

for (const box of document.querySelectorAll(".box")) {
  box.addEventListener("click", () => openBox(box.dataset.key));
  box.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openBox(box.dataset.key); } });
}
$("#docker").addEventListener("click", openContainers);

// ---------------------------------------------------------------- performance and quality
async function loadPerformance() {
  $("#quality").replaceChildren(spinner());
  const p = await api("/api/performance");
  const q = p.quality;
  const ok = q.checks_passed === q.checks;
  $("#quality").replaceChildren(
    el("p", { class: `verdict ${ok ? "ok" : "bad"}` }, q.verdict),
    el("div", { class: "tiles" },
      el("div", { class: "tile" }, el("div", { class: "v" }, `${q.checks_passed} / ${q.checks}`), el("div", { class: "t" }, "quality checks passed"),
        el("div", { class: "l" }, "Soda checks of Silver and Gold, each tied to a quality dimension.")),
      el("div", { class: "tile" }, el("div", { class: "v" }, `${q.goal_minutes_exact} / ${q.goals}`), el("div", { class: "t" }, "goal minutes exact"),
        el("div", { class: "l" }, "Goals whose minute is the one an official match report gives."))));
  $("#slo").replaceChildren(...p.live.map((t) => el("div", { class: "tile" }, el("div", { class: "v" }, t.value), el("div", { class: "l" }, t.title))));
  $("#bench-when").textContent = p.benchmark.generated_at ? `(make benchmark, ${p.benchmark.generated_at})` : "(none yet: make benchmark)";
  $("#bench").replaceChildren(...p.benchmark.cards.map((c) => el("div", { class: `tile${"pass" in c ? (c.pass ? " pass" : " fail") : ""}` },
    el("div", { class: "t" }, c.title), el("div", { class: "v" }, c.value), el("div", { class: "l" }, c.line))));
}

// ---------------------------------------------------------------- export the diagram for slides
function diagramSource() {
  const clone = $("#arch").cloneNode(true);
  clone.classList.remove("moving", "moving-stored");
  clone.setAttribute("width", "1240");
  clone.setAttribute("height", "690");
  return new XMLSerializer().serializeToString(clone);
}
function download(blob, name) {
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
$("#export-svg").addEventListener("click", () => download(new Blob([diagramSource()], { type: "image/svg+xml" }), "matchlens-architecture.svg"));
$("#export-png").addEventListener("click", () => {
  const img = new Image();
  img.onload = () => {
    const c = el("canvas", { width: "2480", height: "1380" });
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0, 2480, 1380);
    c.toBlob((b) => download(b, "matchlens-architecture@2x.png"), "image/png");
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagramSource())}`;
});

// ---------------------------------------------------------------- start
(async () => {
  await loadIcons();
  await Promise.all([loadMatches().catch((e) => showError(e.message)), refreshStatus(), loadPerformance().catch(() => {
    $("#quality").replaceChildren(el("p", { class: "error" }, "Performance and quality are not available yet."));
  })]);
  setInterval(refreshStatus, 5000);
})();
