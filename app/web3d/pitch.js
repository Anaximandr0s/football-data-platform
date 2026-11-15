// MatchLens pitch: one canvas component for Live, Replay and the Player page (docs/product.md, section 8.2).
// Loaded by app/streamlit/pitch.py as a Streamlit custom component v2. No build step, no library.
//
// data (from Python), every coordinate in metres on a 105 x 68 pitch, origin bottom-left:
//   players  {id: [team, shirt, short_name]}            colors {HOME, AWAY}
//   frame    [ts, bx, by, id, x, y, detected, ...]      one second (Live)
//   frames   {ids: [...], t: [ts...], xy: [[bx, by, x0, y0, d0, x1, ...] per second in decimetres, -1 = absent]}
//            with speed (match seconds per real second) and start (ts): a whole match, played in the browser
//   heat     {nx, ny, cells: [share...], color}          shots [[x, y, xe, ye, goal]]   passes [[x, y, xe, ye, ok]]
//   selected player id (ringed)                         arrows {home: "right" | "left"}  clickable (bool)
// Sends back: player (the id of a clicked player).

const L = 105, W = 68;

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
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
      const hit = s.drawn.find((p) => Math.hypot(p.px - x, p.py - y) <= p.r + 3);
      if (hit) setTriggerValue("player", hit.id);
    });
    new ResizeObserver(() => resize(s)).observe(box);
    resize(s);
    requestAnimationFrame((now) => loop(s, now));
  }
  // a whole match is decoded once and keeps playing across reruns; the clock only restarts when start or speed change
  if (data.frames && (data.frames.key !== (s.frames && s.frames.key))) {
    s.frames = data.frames;
    s.clock = null;
  }
  if (s.data && data.frames && (s.data.start !== data.start || s.data.speed !== data.speed)) s.clock = null;
  s.data = data;
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
  if (d.shots) shots(s, d.shots);
  if (d.arrows) attack(s, d.arrows);
  s.drawn = [];
  const frame = d.frames ? playing(s, now) : d.frame;
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
  for (const [x, y, xe, ye, goal] of list) {
    if (xe != null) {
      ctx.strokeStyle = "rgba(244,196,48,0.55)"; ctx.lineWidth = Math.max(1, s.k * 0.2);
      ctx.beginPath(); ctx.moveTo(px(s, x), py(s, y)); ctx.lineTo(px(s, xe), py(s, ye)); ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(px(s, x), py(s, y), s.k * (goal ? 1.5 : 1.1), 0, 2 * Math.PI);
    ctx.fillStyle = goal ? "#f4c430" : "rgba(244,196,48,0.25)"; ctx.fill();
    ctx.strokeStyle = "#f4c430"; ctx.lineWidth = Math.max(1, s.k * 0.2); ctx.stroke();
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
  }
}

// the second shown by a whole match: the clock runs in the browser, positions are interpolated between seconds
function playing(s, now) {
  const f = s.frames, d = s.data;
  if (!s.clock) s.clock = { now0: now, ts0: d.start ?? f.t[0] };
  const ts = s.clock.ts0 + (now - s.clock.now0) / 1000 * (d.speed || 1);
  let i = s.lastIndex || 0;
  if (f.t[i] > ts) i = 0;
  while (i + 1 < f.t.length && f.t[i + 1] <= ts) i++;
  s.lastIndex = i;
  const a = f.xy[i], b = f.xy[Math.min(i + 1, f.xy.length - 1)];
  const gap = f.t[Math.min(i + 1, f.t.length - 1)] - f.t[i];
  const w = gap === 1 ? Math.min(1, Math.max(0, ts - f.t[i])) : 0;    // no interpolation across a camera gap
  const out = a[0] < 0 ? [f.t[i], null, null] : [f.t[i], lerp(a[0], b[0] < 0 ? a[0] : b[0], w) / 10,
                                               lerp(a[1], b[1] < 0 ? a[1] : b[1], w) / 10];
  f.ids.forEach((id, j) => {
    const o = 2 + 3 * j;
    if (a[o] < 0) return;
    const x = b[o] < 0 ? a[o] : lerp(a[o], b[o], w), y = b[o] < 0 ? a[o + 1] : lerp(a[o + 1], b[o + 1], w);
    out.push(id, x / 10, y / 10, a[o + 2]);
  });
  s.canvas.dataset.ts = String(Math.floor(ts));
  return out;
}

const lerp = (a, b, w) => a + (b - a) * w;

function players(s, frame) {
  const ctx = s.ctx, d = s.data, meta = d.players || {}, colors = d.colors || {};
  const r = Math.max(9, s.k * 1.7);
  for (let i = 3; i + 3 < frame.length; i += 4) {
    const id = frame[i], x = frame[i + 1], y = frame[i + 2], detected = frame[i + 3];
    const [team, shirt] = meta[id] || ["", ""];
    const cx = px(s, x), cy = py(s, y);
    ctx.globalAlpha = detected ? 1 : 0.5;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI);
    ctx.fillStyle = colors[team] || "#888"; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(11,20,16,0.9)"; ctx.stroke();
    ctx.fillStyle = ink(colors[team] || "#888"); ctx.font = `800 ${Math.round(r * 1.05)}px system-ui, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(shirt), cx, cy + 0.5);
    if (id === d.selected) {
      ctx.globalAlpha = 1; ctx.lineWidth = 3; ctx.strokeStyle = "#f4c430";
      ctx.beginPath(); ctx.arc(cx, cy, r + 4, 0, 2 * Math.PI); ctx.stroke();
    }
    s.drawn.push({ id, px: cx, py: cy, r });
  }
  ctx.globalAlpha = 1;
  if (frame[1] != null) {
    ctx.beginPath(); ctx.arc(px(s, frame[1]), py(s, frame[2]), Math.max(4, s.k * 0.7), 0, 2 * Math.PI);
    ctx.fillStyle = "#ffffff"; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = "#0b1410"; ctx.stroke();
  }
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
