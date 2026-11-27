// MatchLens Control Center: no framework, no build. Reads /api/*, refreshes every 5 s, two actions: Play and Stop.
"use strict";

const ICONS = ["video", "send", "topology-star-3", "bolt", "broadcast", "bucket", "database", "database-star",
  "chart-bar", "route", "checklist", "heart-rate-monitor", "box", "download", "player-play", "player-stop",
  "info-circle", "alert-triangle", "stack-2", "clock-hour-4", "shield-check", "ball-football", "gauge", "chevron-down",
  "external-link", "x"];
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === "class" ? (e.className = v) : e.setAttribute(k, v);
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
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
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

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

// The diagram's pictures open the real pages: "app:/live_match" -> the app's public address + path.
async function loadConfig() {
  const { base } = await api("/api/config");
  for (const a of document.querySelectorAll("#arch a.thumb")) {
    const [tool, path] = a.dataset.link.split(/:(.*)/s);
    a.setAttribute("href", `${base[tool]}${path}`);
  }
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
  renderReplays(s.replays, s.card_stays_s);
}

function showWarnings(list) {
  const box = $("#warnings");
  box.replaceChildren(...list.map((w) => el("p", {}, icon("alert-triangle"), w)));
  box.hidden = list.length === 0;
}

function replayState(p) {
  if (p.running) return `playing at x${p.speed}`;
  if (p.stopped) return "stopped";
  if (p.partial) return "final whistle: partial replay, live only, not stored";
  if (!p.pipeline) return "final whistle: waiting for Dagster";
  return { SUCCESS: "stored in Gold", FAILURE: "Dagster run failed", CANCELED: "Dagster run cancelled" }[p.pipeline.status]
    || "Dagster is building the match";
}

function renderReplays(plays, staysS) {
  const cards = [];
  for (const p of plays) {
    const run = p.pipeline;
    const fading = p.age !== null && p.age >= staysS - 5;               // the server drops it at staysS
    const share = p.progress ? p.progress.share : 0;
    const card = el("div", { class: `replay${p.running ? "" : " done"}${p.partial ? " partial" : ""}${fading ? " fade" : ""}`, "data-match": p.match_id },
      el("div", { class: "row" },
        el("strong", {}, p.label),
        p.partial ? el("span", { class: "tag", title: "started after kick-off: live only" }, "partial") : null,
        el("span", { class: "clock", "aria-label": "football clock" }, p.progress ? p.progress.clock : "–"),
        el("span", {}, replayState(p)),
        p.running ? el("span", {}, `${Math.round(p.messages_per_s)} messages/s`) : null),
      el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(100 * share)) },
        el("i", { style: `width:${100 * share}%` })),
      run ? el("div", { class: "chips", "aria-label": "Dagster steps" }, ...run.chips.map((c) => el("span", { class: `chip ${c.state.replace(" ", "-")}` }, `${c.label}: ${c.state}`))) : null,
      run && run.status === "SUCCESS" ? el("p", { class: "stored" }, "Stored in Gold: the analysis app shows this match.") : null,
      el("div", { class: "row" }, el("span", { class: "id" }, `replay_id ${p.replay_id}`),
        el("a", { class: "open", href: p.live_url, target: "_blank", rel: "noopener" }, "Open Live page ↗")));
    if (p.running) {
      const stop = el("button", { class: "stop", type: "button" }, icon("player-stop"), "Stop");
      stop.addEventListener("click", async () => {
        stop.disabled = true;
        try { await post("/api/replay/stop", { match: p.match_id }); } catch (e) { showError(e.message); }
        refreshStatus();
      });
      card.querySelector(".row").append(stop);
    }
    cards.push(card);
  }
  $("#replays").replaceChildren(...cards);
  $("#clear").hidden = !plays.some((p) => !p.running);
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

async function play(body, button) {
  showError("");
  button.disabled = true;
  try { await post("/api/replay/start", body); } catch (e) { showError(e.message); }
  button.disabled = false;
  refreshStatus();
}

$("#clock").addEventListener("focus", () => { document.querySelector('input[name="start"][value="clock"]').checked = true; });
$("#play-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const form = new FormData(ev.target);
  const start = form.get("start");
  play({ match: $("#match").value, speed: Number(form.get("speed")), start: start === "clock" ? $("#clock").value : start }, $("#play-btn"));
});
$("#clear").addEventListener("click", async () => {
  try { await post("/api/replay/clear", {}); } catch (e) { showError(e.message); }
  refreshStatus();
});
$("#play-full").addEventListener("click", () => play({ match: $("#match").value, speed: 60, start: "kickoff" }, $("#play-full")));

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
      b.numbers.length ? el("div", { class: "nums" }, ...b.numbers.map((n) => el("div", { class: "tile" }, el("div", { class: "v" }, n.value), el("div", { class: "l" }, n.label)))) : null,
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

// ---------------------------------------------------------------- performance and quality: journey, 5 cards, details
async function loadPerformance() {
  $("#hero").replaceChildren(spinner());
  const p = await api("/api/performance");
  $("#journey").replaceChildren(...p.journey.map((step, i) => el("li", { class: i % 2 ? "time" : "" }, step)));
  $("#hero").replaceChildren(...p.hero.map((h) => el("div", { class: "card2" },
    el("div", { class: "head" }, icon(h.icon), h.title),
    el("div", { class: "big" }, h.value),
    el("div", { class: "line" }, h.line),
    el("div", { class: "src" }, `Source: ${h.source}`))));
  $("#slo-details").replaceChildren(...p.details.map((d) => el("div", { class: `tile${"pass" in d ? (d.pass ? " pass" : " fail") : ""}` },
    el("div", { class: "t" }, d.title), el("div", { class: "v" }, d.value), el("div", { class: "l" }, d.line),
    el("div", { class: "src" }, d.period))));
  $("#now").replaceChildren(...p.now.map((t) => el("div", { class: "tile" }, el("div", { class: "v" }, t.value),
    el("div", { class: "l" }, t.title), el("div", { class: "src" }, t.period))));
}

// ---------------------------------------------------------------- export the diagram for slides
// Pictures and logos become data: URLs in the copy, so the SVG and the PNG need no server.
async function diagramSource() {
  const clone = $("#arch").cloneNode(true);
  clone.classList.remove("moving", "moving-stored");
  clone.setAttribute("width", "1600");
  clone.setAttribute("height", "900");
  await Promise.all([...clone.querySelectorAll("image")].map(async (img) => {
    const blob = await (await fetch(img.getAttribute("href"))).blob();
    const data = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(blob); });
    img.setAttribute("href", data);
  }));
  return new XMLSerializer().serializeToString(clone);
}
function download(blob, name) {
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
$("#export-svg").addEventListener("click", async () => download(new Blob([await diagramSource()], { type: "image/svg+xml" }), "matchlens-architecture.svg"));
$("#export-png").addEventListener("click", async () => {
  const src = await diagramSource();
  const img = new Image();
  img.onload = () => {
    const c = el("canvas", { width: "3200", height: "1800" });
    c.getContext("2d").drawImage(img, 0, 0, 3200, 1800);
    c.toBlob((b) => download(b, "matchlens-architecture@2x.png"), "image/png");
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(src)}`;
});

// ---------------------------------------------------------------- start
(async () => {
  await loadIcons();
  await Promise.all([loadConfig(), loadMatches().catch((e) => showError(e.message)), refreshStatus(), loadPerformance().catch(() => {
    $("#hero").replaceChildren(el("p", { class: "error" }, "Performance and quality are not available yet."));
  })]);
  setInterval(refreshStatus, 5000);
})();
