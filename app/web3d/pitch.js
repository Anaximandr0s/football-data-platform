// MatchLens pitch: one canvas component for Live, Replay and the Player page (docs/product.md, section 8.2).
// Loaded by app/streamlit/pitch.py as a Streamlit custom component v2. No build step; the one library, d3-delaunay
// (Voronoi cells), is the vendored file d3-delaunay.min.js, loaded before this one (globalThis.d3).
//
// data (from Python), every coordinate in metres on a 105 x 68 pitch, origin bottom-left:
//   players  {id: [team, shirt, short_name, goalkeeper]} colors {HOME, AWAY}
//   frame    [ts, bx, by, id, x, y, detected, ...]      one second (Live)
//   frames   {key, ids: [...], t: [ts...], xy: [[bx, by, bz, x0, y0, d0, x1, ...] per tracked second, centimetres,
//            null = absent]}: a whole match, sent once; later runs send only {key} and the browser keeps its copy
//   replay   {start, end, clock: [label of every second from t[0]], names: [HOME, AWAY],
//            goals: [[goal second, team, text, scorer]], shots: [[ts, team, text]], events: [[ts, caption]]}:
//            the Replay controls (play/pause, speed, scrubber with goal and shot marks, GOAL! effect, smooth, trails,
//            names, detected only, Voronoi, legend, keys: space, left, right), all in the browser
//   heat     {nx, ny, cells: [share...], color}          shots [[x, y, xe, ye, goal, color?]]   passes [[x, y, xe, ye, ok]]
//   network  {color, nodes: [[x, y, passes, label, hub]], edges: [[x1, y1, x2, y2, passes]]}
//   selected player id (ringed)    arrows {home: "right" | "left", names: {HOME, AWAY}}    clickable (bool)
// Sends back: player (trigger: the id of a clicked player; on Replay the state pick {player, n} instead); time (state: the replay second, every 2.5 s of match
// time while playing, at most every 2 s, and at once on pause, seek or click); reload (trigger: the frames key, when only the key arrived and the
// browser has no copy, after a remount).

const L = 105, W = 68;

export default function (component) {
  const { data, setTriggerValue, setStateValue, parentElement } = component;
  let s = parentElement.__pitch;
  if (!s) {
    // parentElement may be a shadow root (style isolation): the canvas lives in a div of its own, which is measured
    const box = document.createElement("div");
    box.style.width = "100%";
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.display = "block";
    canvas.style.borderRadius = "10px";
    canvas.dataset.testid = "ml-pitch";
    box.appendChild(canvas);
    parentElement.appendChild(box);
    s = parentElement.__pitch = box.__pitch = { box, canvas, ctx: canvas.getContext("2d"), drawn: [], data: null,
                                                frames: null, clock: null, fpsCount: 0, fpsSince: performance.now() };
    canvas.addEventListener("click", (e) => {
      if (!s.data || !s.data.clickable) return;
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      // the nearest player; while a replay plays, the dots move fast: the click area grows with the speed
      const slack = 3 + (s.rp && (s.rp.playing || s.rp.resumeAt) ? 2 * s.rp.speed : 0);
      const dist = (p) => Math.hypot(p.px - x, p.py - y);
      const hit = s.drawn.filter((p) => dist(p) <= p.r + slack).sort((a, b) => dist(a) - dist(b))[0];
      if (!hit) return;
      if (s.rp) {                      // Replay reruns Python often while playing: a state survives, a trigger may not
        s.picks = (s.picks || 0) + 1;
        setStateValue("pick", { player: hit.id, n: s.picks });
        report(s, true);
        return;
      }
      setTriggerValue("player", hit.id);
    });
    new ResizeObserver(() => resize(s)).observe(box);
    resize(s);
    requestAnimationFrame((now) => loop(s, now));
  }
  s.setState = setStateValue;
  // a whole match is decoded once and keeps playing across reruns
  if (data.frames && data.frames.xy && data.frames.key !== (s.frames && s.frames.key)) {
    s.frames = data.frames;
    s.rp = null;
  } else if (data.frames && !data.frames.xy && data.frames.key !== (s.frames && s.frames.key)) {
    setTriggerValue("reload", data.frames.key);           // remounted without our copy: ask Python for the match
  }
  s.data = data;
  if (data.replay && s.frames && s.frames.xy) controls(s);
}

function resize(s) {
  const w = s.box.clientWidth || 700, ratio = window.devicePixelRatio || 1;
  s.cssW = w; s.cssH = Math.round(w * (W + 6) / (L + 6));
  s.canvas.width = Math.round(w * ratio); s.canvas.height = Math.round(s.cssH * ratio);
  s.canvas.style.height = s.cssH + "px";
  s.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  s.k = w / (L + 6);                     // pixels per metre, with a 3 m margin around the pitch
}

const px = (s, x) => (x + 3) * s.k;
const py = (s, y) => (W + 3 - y) * s.k;

function loop(s, now) {
  draw(s, now);
  s.fpsCount += 1;
  if (now - s.fpsSince >= 1000) {
    s.canvas.dataset.fps = String(Math.round(s.fpsCount * 1000 / (now - s.fpsSince)));
    s.fpsCount = 0; s.fpsSince = now;
  }
  requestAnimationFrame((t) => loop(s, t));
}

function draw(s, now) {
  const d = s.data;
  if (!d) return;
  const ctx = s.ctx;
  ctx.clearRect(0, 0, s.cssW, s.cssH);
  field(s);
  if (d.heat) heat(s, d.heat);
  if (d.passes) arrows(s, d.passes, "#e8f0ea");
  if (d.network) network(s, d.network);
  if (d.shots) shots(s, d.shots);
  if (d.arrows) attack(s, d.arrows);
  s.drawn = [];
  if (d.replay && s.rp) return replayFrame(s, now);
  const frame = d.frame;
  if (frame) players(s, frame);
  if (d.message) banner(s, d.message);
}

function field(s) {
  const ctx = s.ctx, k = s.k;
  ctx.fillStyle = "#123524";
  ctx.fillRect(0, 0, s.cssW, s.cssH);
  for (let i = 0; i < 10; i += 2) {                       // mown stripes, 10.5 m wide
    ctx.fillStyle = "#15402b";
    ctx.fillRect(px(s, i * 10.5), py(s, W), 10.5 * k, W * k);
  }
  ctx.strokeStyle = "rgba(232,240,234,0.75)"; ctx.lineWidth = Math.max(1, k * 0.15);
  const rect = (x, y, w, h) => ctx.strokeRect(px(s, x), py(s, y + h), w * k, h * k);
  rect(0, 0, L, W);
  ctx.beginPath(); ctx.moveTo(px(s, L / 2), py(s, 0)); ctx.lineTo(px(s, L / 2), py(s, W)); ctx.stroke();
  ctx.beginPath(); ctx.arc(px(s, L / 2), py(s, W / 2), 9.15 * k, 0, 2 * Math.PI); ctx.stroke();
  for (const left of [true, false]) {
    const x0 = left ? 0 : L;
    const dir = left ? 1 : -1;
    rect(left ? 0 : L - 16.5, W / 2 - 20.16, 16.5, 40.32);
    rect(left ? 0 : L - 5.5, W / 2 - 9.16, 5.5, 18.32);
    rect(left ? -2 : L, W / 2 - 3.66, 2, 7.32);
    ctx.beginPath(); ctx.arc(px(s, x0 + dir * 11), py(s, W / 2), Math.max(1, k * 0.3), 0, 2 * Math.PI);
    ctx.fillStyle = "rgba(232,240,234,0.75)"; ctx.fill();
  }
}

function heat(s, h) {
  const ctx = s.ctx, cw = L / h.nx, ch = W / h.ny, top = Math.max(...h.cells, 1e-9);
  h.cells.forEach((v, i) => {
    if (!v) return;
    const zx = i % h.nx, zy = Math.floor(i / h.nx);
    ctx.globalAlpha = 0.06 + 0.64 * v / top;
    ctx.fillStyle = h.color;
    ctx.fillRect(px(s, zx * cw), py(s, (zy + 1) * ch), cw * s.k, ch * s.k);
  });
  ctx.globalAlpha = 1;
}

function arrows(s, list, color) {
  const ctx = s.ctx;
  for (const [x, y, xe, ye, ok] of list) {
    if (xe == null || ye == null) continue;
    ctx.strokeStyle = color; ctx.globalAlpha = ok ? 0.85 : 0.35; ctx.lineWidth = Math.max(1, s.k * 0.25);
    const a = Math.atan2(py(s, ye) - py(s, y), px(s, xe) - px(s, x)), hd = s.k * 1.4;
    ctx.beginPath(); ctx.moveTo(px(s, x), py(s, y)); ctx.lineTo(px(s, xe), py(s, ye)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(px(s, xe), py(s, ye));
    ctx.lineTo(px(s, xe) - hd * Math.cos(a - 0.45), py(s, ye) - hd * Math.sin(a - 0.45));
    ctx.lineTo(px(s, xe) - hd * Math.cos(a + 0.45), py(s, ye) - hd * Math.sin(a + 0.45));
    ctx.closePath(); ctx.fillStyle = color; ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function shots(s, list) {
  const ctx = s.ctx;
  for (const [x, y, xe, ye, goal, color] of list) {
    const c = color || "#f4c430";
    if (xe != null) {
      ctx.strokeStyle = c; ctx.globalAlpha = 0.45; ctx.lineWidth = Math.max(1, s.k * 0.2);
      ctx.beginPath(); ctx.moveTo(px(s, x), py(s, y)); ctx.lineTo(px(s, xe), py(s, ye)); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.beginPath(); ctx.arc(px(s, x), py(s, y), s.k * (goal ? 1.6 : 1.1), 0, 2 * Math.PI);
    ctx.fillStyle = goal ? c : "rgba(11,20,16,0.6)"; ctx.fill();
    ctx.strokeStyle = goal ? "#f4c430" : c; ctx.lineWidth = Math.max(1.5, s.k * (goal ? 0.4 : 0.25)); ctx.stroke();
  }
}

// pass network: lines between average positions (width = passes), nodes sized by passes made, the hub ringed in gold
function network(s, n) {
  const ctx = s.ctx, top = Math.max(1, ...n.edges.map((e) => e[4])), most = Math.max(1, ...n.nodes.map((p) => p[2]));
  for (const [x1, y1, x2, y2, w] of n.edges) {
    ctx.strokeStyle = n.color; ctx.globalAlpha = 0.25 + 0.6 * w / top; ctx.lineWidth = Math.max(1, s.k * 1.1 * w / top);
    ctx.beginPath(); ctx.moveTo(px(s, x1), py(s, y1)); ctx.lineTo(px(s, x2), py(s, y2)); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  for (const [x, y, passes, label, isHub] of n.nodes) {
    const r = s.k * (1.2 + 1.6 * Math.sqrt(passes / most));
    ctx.beginPath(); ctx.arc(px(s, x), py(s, y), r, 0, 2 * Math.PI);
    ctx.fillStyle = n.color; ctx.fill();
    ctx.lineWidth = isHub ? 3.5 : 1.5; ctx.strokeStyle = isHub ? "#f4c430" : "rgba(11,20,16,0.9)"; ctx.stroke();
    ctx.fillStyle = ink(n.color); ctx.font = `800 ${Math.round(Math.max(10, r * 0.95))}px system-ui, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(label), px(s, x), py(s, y) + 0.5);
  }
}

function attack(s, a) {
  const ctx = s.ctx, y = -1.6, mid = L / 2;
  for (const [team, sign] of [["HOME", a.home === "right" ? 1 : -1], ["AWAY", a.home === "right" ? -1 : 1]]) {
    const x0 = mid - sign * 6, x1 = mid + sign * 6;
    ctx.strokeStyle = (s.data.colors || {})[team] || "#e8f0ea"; ctx.lineWidth = Math.max(1.5, s.k * 0.35);
    const yy = team === "HOME" ? y : W + 1.6;
    ctx.beginPath(); ctx.moveTo(px(s, x0), py(s, yy)); ctx.lineTo(px(s, x1), py(s, yy)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(px(s, x1), py(s, yy));
    ctx.lineTo(px(s, x1 - sign * 1.4), py(s, yy) - s.k * 0.9); ctx.lineTo(px(s, x1 - sign * 1.4), py(s, yy) + s.k * 0.9);
    ctx.closePath(); ctx.fillStyle = ctx.strokeStyle; ctx.fill();
    const name = (a.names || {})[team];
    if (name) {                                          // the team's name beside its arrow, on the side it comes from
      ctx.font = `700 ${Math.round(Math.max(10, s.k * 1.25))}px system-ui, sans-serif`; ctx.textBaseline = "middle";
      ctx.textAlign = sign > 0 ? "right" : "left";
      ctx.fillText(name, px(s, x0 - sign * 1.2), py(s, yy));
    }
  }
}

const lerp = (a, b, w) => a + (b - a) * w;

function players(s, frame, opt = {}) {
  const ctx = s.ctx, d = s.data, meta = d.players || {}, colors = d.colors || {};
  const r = Math.max(9, s.k * 1.7);
  for (let i = 3; i + 3 < frame.length; i += 4) {
    const id = frame[i], x = frame[i + 1], y = frame[i + 2], detected = frame[i + 3];
    const [team, shirt, name, keeper] = meta[id] || ["", "", "", false];
    const cx = px(s, x), cy = py(s, y);
    const grey = opt.detectedOnly && !detected;
    ctx.globalAlpha = grey ? 0.35 : detected ? 1 : 0.5;
    ctx.beginPath();
    if (keeper) ctx.roundRect(cx - r, cy - r, 2 * r, 2 * r, r * 0.35);   // goalkeeper: a square, as in the legend
    else ctx.arc(cx, cy, r, 0, 2 * Math.PI);
    ctx.fillStyle = grey ? "#5b6b62" : colors[team] || "#888"; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(11,20,16,0.9)"; ctx.stroke();
    ctx.fillStyle = ink(colors[team] || "#888"); ctx.font = `800 ${Math.round(r * 1.05)}px system-ui, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(shirt), cx, cy + 0.5);
    if (opt.names && name) {
      ctx.font = `600 ${Math.round(Math.max(10, r * 0.8))}px system-ui, sans-serif`; ctx.fillStyle = "#e8f0ea";
      ctx.fillText(String(name), cx, cy + r + Math.max(8, r * 0.7));
    }
    if (id === d.selected) {
      ctx.globalAlpha = 1; ctx.lineWidth = 3; ctx.strokeStyle = "#f4c430";
      ctx.beginPath();
      if (keeper) ctx.roundRect(cx - r - 4, cy - r - 4, 2 * r + 8, 2 * r + 8, r * 0.45);
      else ctx.arc(cx, cy, r + 4, 0, 2 * Math.PI);
      ctx.stroke();
    }
    s.drawn.push({ id, px: cx, py: cy, r });
  }
  ctx.globalAlpha = 1;
  if (frame[1] != null) ball(s, frame[1], frame[2], opt.ballZ || 0);
}

// the ball: a shadow on the grass where it is, and the ball itself bigger and higher the more it is in the air
function ball(s, x, y, z) {
  const ctx = s.ctx, h = Math.min(Math.max(z, 0), 8), r = Math.max(5.5, s.k * 0.95) * (1 + h / 8);
  const cx = px(s, x), cy = py(s, y);
  ctx.beginPath(); ctx.ellipse(cx, cy, r * 0.9, r * 0.45, 0, 0, 2 * Math.PI);
  ctx.fillStyle = `rgba(0,0,0,${0.45 - h * 0.03})`; ctx.fill();
  const lift = h * s.k * 0.35;
  ctx.beginPath(); ctx.arc(cx, cy - lift, r, 0, 2 * Math.PI);
  ctx.fillStyle = "#ffffff"; ctx.fill(); ctx.lineWidth = 2.5; ctx.strokeStyle = "#0b1410"; ctx.stroke();
}

// dark number on a light shirt colour, white otherwise (same rule as the shirt cards)
function ink(color) {
  const c = /^#([0-9a-f]{6})$/i.exec(color);
  if (!c) return "#ffffff";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(c[1].slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 ? "#0b1410" : "#ffffff";
}

function banner(s, text) {
  const ctx = s.ctx;
  ctx.fillStyle = "rgba(11,20,16,0.82)";
  ctx.fillRect(px(s, L / 2 - 30), py(s, W / 2 + 4), 60 * s.k, 8 * s.k);
  ctx.fillStyle = "#f4c430"; ctx.font = `700 ${Math.round(s.k * 2.6)}px system-ui, sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, px(s, L / 2), py(s, W / 2));
}


// ---------------------------------------------------------------- Replay: a whole match played in the browser
const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const BALL = 3;             // ball x, y, z open each second; then x, y, detected per player
const TRAIL_S = 6;          // seconds of trail behind each player
const BALL_TRAIL_S = 1.2;   // seconds of trail behind the ball
const GOAL_PAUSE_MS = 3000; // the replay stops this long on a goal
// the panel (Python) gets the replay time every REPORT_MATCH_S of match time, at most every 2 s: with the rerun
// itself it stays within about 5 s of match time at 8x
const REPORT_MATCH_S = 2.5;
const reportEvery = (speed) => Math.min(2000, REPORT_MATCH_S * 1000 / speed);

const TOGGLES = [
  ["smooth", "Smooth movement", "Draw the straight line between two consecutive seconds (1 Hz data) at the screen's " +
   "frame rate, never across a camera gap. Off: the raw jumps of one position per second."],
  ["trails", "Trails", "Where each player was in the last 6 seconds."],
  ["names", "Names", "The player's name under his shirt number."],
  ["detectedOnly", "Detected only", "Grey out the positions SkillCorner estimated (the player was off the TV picture)."],
  ["voronoi", "Voronoi", "Each cell holds the part of the pitch nearer to its player than to any other (space control)."],
];

const CSS = `
.rp{font:13px system-ui,sans-serif;color:#e8f0ea;margin-top:8px;display:flex;flex-direction:column;gap:8px}
.rp-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.rp button,.rp select{background:#12221a;color:#e8f0ea;border:1px solid #23392d;border-radius:6px;padding:4px 10px;
  font:600 13px system-ui,sans-serif;cursor:pointer}
.rp button.on{background:#15803d;border-color:#15803d}
.rp .play{width:44px;font-size:15px}
.rp .clock{font:700 18px system-ui,sans-serif;min-width:118px;font-variant-numeric:tabular-nums}
.rp .score{font:700 15px system-ui,sans-serif}
.rp .event{color:#b9c8bf;min-height:18px}
.rp .track{position:relative;flex:1;min-width:220px;height:26px}
.rp .track input{position:absolute;inset:0;width:100%;margin:0;accent-color:#15803d}
.rp .mark{position:absolute;top:-3px;width:12px;height:12px;border-radius:50%;border:2px solid #0b1410;
  transform:translateX(-50%);cursor:pointer;z-index:2}
.rp .shot{position:absolute;top:0;width:7px;height:7px;border-radius:50%;background:#0b1410;border:2px solid;
  transform:translateX(-50%);cursor:pointer;z-index:1}
.rp .goal{font-size:12px;padding:2px 8px}
.rp .legend{display:flex;flex-wrap:wrap;gap:6px 16px;padding:8px 10px;border:1px solid #23392d;border-radius:8px;
  background:#12221a;color:#b9c8bf;font-size:12px}
.rp .legend span{display:inline-flex;align-items:center;gap:6px}
.rp .dot{width:12px;height:12px;border-radius:50%;display:inline-block;border:1.5px solid #0b1410}
.rp .sq{border-radius:3px}
.rp .keys{color:#7f9488;font-size:12px}`;

function controls(s) {
  const d = s.data, rp0 = d.replay, f = s.frames;
  if (!s.rp) {
    s.rp = { ts: rp0.start ?? f.t[0], playing: false, speed: 1, last: null, reported: 0, smooth: true, trails: false,
             names: false, detectedOnly: false, voronoi: false, built: false, goalFx: null, resumeAt: null,
             shownSec: null };
  }
  if (s.rp.built) return;
  s.rp.built = true;
  const colors = d.colors || {}, [home, away] = rp0.names;
  const root = document.createElement("div");
  root.className = "rp";
  root.innerHTML = `<style>${CSS}</style>
    <div class="rp-row"><button class="play" title="Play / pause (space)">▶</button><span class="clock"></span>
      <span class="score"></span><span style="flex:1"></span>
      <select class="speed" title="Playback speed">${SPEEDS.map((v) => `<option value="${v}">${v}x</option>`).join("")}</select></div>
    <div class="rp-row"><div class="track"><input type="range" step="1" title="Drag to any second (left / right: 5 s)"></div></div>
    <div class="rp-row event"></div>
    <div class="rp-row goals"></div>
    <div class="rp-row toggles"></div>
    <div class="legend">
      <span><i class="dot" style="background:${colors.HOME}"></i>${home}</span>
      <span><i class="dot" style="background:${colors.AWAY}"></i>${away}</span>
      <span><i class="dot" style="background:${colors.HOME};opacity:.5"></i>faded: position estimated by SkillCorner</span>
      <span><i class="dot sq" style="background:#b9c8bf"></i>goalkeeper (GK)</span>
      <span><i class="dot" style="background:#fff;border-width:2.5px"></i>ball: bigger and higher when in the air</span>
      <span>→ direction of attack, both halves</span>
      <span>● goal · ○ shot on the timeline</span>
    </div>
    <div class="keys">Keys: space = play / pause, ← → = 5 s back / forward.</div>`;
  s.box.appendChild(root);
  const $ = (q) => root.querySelector(q);
  s.ui = { play: $(".play"), clock: $(".clock"), score: $(".score"), range: $("input"), speed: $(".speed"),
           event: $(".event") };
  s.ui.speed.value = "1";
  s.ui.range.min = String(f.t[0]); s.ui.range.max = String(rp0.end); s.ui.range.value = String(s.rp.ts);
  s.ui.play.onclick = () => toggle(s);
  s.ui.speed.onchange = () => { s.rp.speed = Number(s.ui.speed.value); };
  s.ui.range.oninput = () => seek(s, Number(s.ui.range.value), false);
  s.ui.range.onchange = () => report(s, true);
  const span = Math.max(1, rp0.end - f.t[0]), at = (ts) => `${100 * (ts - f.t[0]) / span}%`;
  for (const [ts, team, text] of rp0.shots || []) {
    const m = document.createElement("span");
    m.className = "shot"; m.title = `Shot ${text}`; m.style.left = at(ts); m.style.borderColor = colors[team] || "#e8f0ea";
    m.onclick = () => seek(s, Math.max(f.t[0], ts - 5), true);
    $(".track").appendChild(m);
  }
  for (const [ts, team, text] of rp0.goals) {
    const jump = () => seek(s, Math.max(f.t[0], ts - 10), true);
    const mark = document.createElement("span");
    mark.className = "mark"; mark.title = `Goal ${text}`; mark.style.left = at(ts);
    mark.style.background = colors[team] || "#f4c430"; mark.onclick = jump;
    $(".track").appendChild(mark);
    const chip = document.createElement("button");
    chip.className = "goal"; chip.textContent = `⚽ ${text}`; chip.title = "Jump 10 s before the ball goes in";
    chip.onclick = jump; chip.style.borderColor = colors[team] || "#23392d";
    $(".goals").appendChild(chip);
  }
  for (const [key, text, help] of TOGGLES) {
    const b = document.createElement("button");
    b.textContent = text; b.className = s.rp[key] ? "on" : ""; b.title = help;
    b.dataset.toggle = key;
    b.onclick = () => { s.rp[key] = !s.rp[key]; b.className = s.rp[key] ? "on" : ""; };
    $(".toggles").appendChild(b);
  }
  keys(s);
}

function toggle(s) {
  s.rp.playing = !s.rp.playing; s.rp.last = null; s.rp.resumeAt = null; s.rp.goalFx = null;
  if (!s.rp.playing) report(s, true);
}

function seek(s, ts, now) {
  s.rp.ts = Math.max(s.frames.t[0], Math.min(s.data.replay.end, ts));
  s.rp.last = null; s.rp.goalFx = null; s.rp.resumeAt = null; s.rp.shownSec = Math.floor(s.rp.ts);
  if (now) report(s, true);
}

// space = play / pause, left / right = 5 s; not while the visitor types in a field of the page
function keys(s) {
  if (document.__matchlensKeys) document.removeEventListener("keydown", document.__matchlensKeys);
  document.__matchlensKeys = (e) => {
    if (!s.rp || !s.canvas.isConnected) return;
    const tag = (e.composedPath()[0] || {}).tagName || "";
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) && !(e.composedPath()[0] === s.ui.range)) return;
    if (e.code === "Space") {
      e.preventDefault();
      if (tag === "BUTTON") e.composedPath()[0].blur();      // or the focused button is clicked too, on key up
      toggle(s);
    }
    else if (e.code === "ArrowLeft") { e.preventDefault(); seek(s, s.rp.ts - 5, true); }
    else if (e.code === "ArrowRight") { e.preventDefault(); seek(s, s.rp.ts + 5, true); }
  };
  document.addEventListener("keydown", document.__matchlensKeys);
}

// the replay second goes back to Python (stats panel): at once when asked, otherwise every 2.5 s of match time
function report(s, now) {
  const t = performance.now();
  if (!now && t - s.rp.reported < reportEvery(s.rp.speed)) return;
  s.rp.reported = t;
  if (s.setState) s.setState("time", Math.floor(s.rp.ts));
}

function indexAt(t, ts) {            // last tracked second <= ts (binary search)
  let lo = 0, hi = t.length - 1;
  if (ts < t[0]) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (t[mid] <= ts) lo = mid; else hi = mid - 1;
  }
  return lo;
}

function at(xy, o) { return xy[o] == null ? null : [xy[o] / 100, xy[o + 1] / 100]; }

// where object o is at time ts: interpolated between two consecutive tracked seconds (smooth), never across a gap
function sample(s, ts, o) {
  const f = s.frames, sec = Math.floor(ts), i = indexAt(f.t, sec);
  if (i < 0 || f.t[i] !== sec) return null;
  const p = at(f.xy[i], o);
  if (!p) return null;
  const next = i + 1 < f.t.length && f.t[i + 1] === sec + 1 ? at(f.xy[i + 1], o) : null;
  const w = s.rp.smooth && next ? ts - sec : 0;
  return next ? [lerp(p[0], next[0], w), lerp(p[1], next[1], w)] : p;
}

function lastBefore(list, sec) {    // the last [ts, ...] item with ts <= sec (list sorted by ts)
  let out = null;
  for (const item of list) { if (item[0] <= sec) out = item; else break; }
  return out;
}

function replayFrame(s, now) {
  const f = s.frames, d = s.data, rp = s.rp, end = d.replay.end;
  if (!rp.playing && rp.resumeAt && now >= rp.resumeAt) { rp.playing = true; rp.resumeAt = null; rp.last = null; }
  if (rp.playing) {
    if (rp.last != null) rp.ts = Math.min(end, rp.ts + (now - rp.last) / 1000 * rp.speed);
    rp.last = now;
    if (rp.ts >= end) { rp.playing = false; report(s, true); } else report(s, false);
  }
  const ts = rp.ts, sec = Math.floor(ts), i = indexAt(f.t, sec);
  // a goal crossed while playing: the net flashes, a banner, and the replay waits GOAL_PAUSE_MS
  if (rp.playing && rp.shownSec != null && sec > rp.shownSec) {
    const goal = d.replay.goals.find((g) => g[0] > rp.shownSec && g[0] <= sec);
    if (goal) {
      rp.ts = goal[0]; rp.playing = false; rp.resumeAt = now + GOAL_PAUSE_MS; rp.goalFx = { goal, until: rp.resumeAt };
      report(s, true);
    }
  }
  rp.shownSec = Math.floor(rp.ts);
  s.canvas.dataset.ts = String(rp.shownSec);
  s.ui.play.textContent = rp.playing || rp.resumeAt ? "❚❚" : "▶";
  if (document.activeElement !== s.ui.range) s.ui.range.value = String(rp.shownSec);
  s.ui.clock.textContent = d.replay.clock[Math.max(0, Math.min(d.replay.clock.length - 1, rp.shownSec - f.t[0]))] || "";
  const [home, away] = score(d.replay.goals, rp.shownSec);
  s.ui.score.textContent = `${d.replay.names[0]} ${home} - ${away} ${d.replay.names[1]}`;
  const ev = lastBefore(d.replay.events || [], rp.shownSec);
  s.ui.event.textContent = ev ? `Last event: ${ev[1]}` : "";
  if (rp.goalFx) goalFlash(s, rp.goalFx, now);
  if (i < 0 || f.t[i] !== rp.shownSec) { banner(s, "No tracking: camera off the pitch"); return; }
  const t = rp.ts, frame = [rp.shownSec];
  const b = sample(s, t, 0);
  frame.push(b ? b[0] : null, b ? b[1] : null);
  const points = [];
  f.ids.forEach((id, j) => {
    const o = BALL + 3 * j, p = sample(s, t, o);
    if (!p) return;
    frame.push(id, p[0], p[1], f.xy[i][o + 2] === 1);
    points.push([id, p[0], p[1]]);
  });
  if (rp.voronoi && globalThis.d3 && points.length > 2) voronoi(s, points);
  if (rp.trails) trails(s, i, points);
  if (b) ballTrail(s, t);
  const z = f.xy[i][2] == null ? 0 : f.xy[i][2] / 100;
  players(s, frame, { names: rp.names, detectedOnly: rp.detectedOnly, ballZ: z });
  if (rp.goalFx) goalBanner(s, rp.goalFx);
}

function score(goals, sec) {
  const done = goals.filter((g) => g[0] <= sec), home = done.filter((g) => g[1] === "HOME").length;
  return [home, done.length - home];
}

function ballTrail(s, t) {
  const ctx = s.ctx, pts = [];
  for (let k = 8; k >= 0; k--) {
    const p = sample(s, t - BALL_TRAIL_S * k / 8, 0);
    if (p) pts.push(p);
  }
  if (pts.length < 2) return;
  ctx.strokeStyle = "#ffffff"; ctx.lineWidth = Math.max(2, s.k * 0.45); ctx.lineCap = "round";
  for (let k = 1; k < pts.length; k++) {
    ctx.globalAlpha = 0.08 + 0.5 * k / pts.length;
    ctx.beginPath(); ctx.moveTo(px(s, pts[k - 1][0]), py(s, pts[k - 1][1])); ctx.lineTo(px(s, pts[k][0]), py(s, pts[k][1]));
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

// the goal the ball went into flashes gold (HOME attacks toward x = 105 in the Silver frame)
function goalFlash(s, fx, now) {
  const ctx = s.ctx, right = fx.goal[1] === "HOME", pulse = 0.35 + 0.35 * Math.abs(Math.sin(now / 120));
  ctx.globalAlpha = pulse; ctx.fillStyle = "#f4c430";
  ctx.fillRect(px(s, right ? L : -2.5), py(s, W / 2 + 3.66), 2.5 * s.k, 7.32 * s.k);
  ctx.globalAlpha = pulse * 0.4;
  ctx.fillRect(px(s, right ? L - 16.5 : 0), py(s, W / 2 + 20.16), 16.5 * s.k, 40.32 * s.k);
  ctx.globalAlpha = 1;
}

function goalBanner(s, fx) {
  const ctx = s.ctx, d = s.data, [home, away] = score(d.replay.goals, fx.goal[0]);
  ctx.fillStyle = "rgba(11,20,16,0.88)";
  ctx.fillRect(px(s, L / 2 - 34), py(s, W / 2 + 7), 68 * s.k, 14 * s.k);
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillStyle = "#f4c430"; ctx.font = `900 ${Math.round(s.k * 4.4)}px system-ui, sans-serif`;
  ctx.fillText("GOAL!", px(s, L / 2), py(s, W / 2 + 3));
  ctx.fillStyle = "#e8f0ea"; ctx.font = `700 ${Math.round(s.k * 2)}px system-ui, sans-serif`;
  ctx.fillText(`${fx.goal[3]} · ${d.replay.names[0]} ${home} - ${away} ${d.replay.names[1]}`, px(s, L / 2), py(s, W / 2 - 3));
}

function trails(s, i, points) {
  const f = s.frames, ctx = s.ctx, meta = s.data.players || {}, colors = s.data.colors || {};
  for (const [id, x, y] of points) {
    const o = BALL + 3 * f.ids.indexOf(id), path = [];
    for (let j = i; j >= Math.max(0, i - TRAIL_S) && f.t[i] - f.t[j] === i - j; j--) {
      const p = at(f.xy[j], o);
      if (!p) break;
      path.unshift(p);
    }
    path.push([x, y]);
    if (path.length < 2) continue;
    ctx.strokeStyle = colors[(meta[id] || [])[0]] || "#e8f0ea"; ctx.globalAlpha = 0.55;
    ctx.lineWidth = Math.max(1.5, s.k * 0.35); ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(px(s, path[0][0]), py(s, path[0][1]));
    for (const [x2, y2] of path.slice(1)) ctx.lineTo(px(s, x2), py(s, y2));
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

// each cell holds the points of the pitch nearer to its player than to any other (S1 of docs/product.md)
function voronoi(s, points) {
  const ctx = s.ctx, meta = s.data.players || {}, colors = s.data.colors || {};
  const vor = globalThis.d3.Delaunay.from(points.map((p) => [p[1], p[2]])).voronoi([0, 0, L, W]);
  points.forEach(([id], k) => {
    const cell = vor.cellPolygon(k);
    if (!cell) return;
    ctx.beginPath();
    cell.forEach(([x, y], n) => (n ? ctx.lineTo(px(s, x), py(s, y)) : ctx.moveTo(px(s, x), py(s, y))));
    ctx.closePath();
    ctx.fillStyle = colors[(meta[id] || [])[0]] || "#888"; ctx.globalAlpha = 0.18; ctx.fill();
    ctx.strokeStyle = "rgba(232,240,234,0.35)"; ctx.globalAlpha = 1; ctx.lineWidth = 1; ctx.stroke();
  });
}
