"use strict";

/* The page itself does no circuit maths. It loads mesh_solver_general.py into Pyodide,
   sends it the circuit as JSON through solve_web(), and draws what comes back. */

/* The Pyodide version is set once, in the <script> tag in index.html. */
const PYODIDE_URL = document.querySelector('script[src$="/pyodide.js"]').src.replace(/pyodide\.js$/, "");
const PROGRAM_FILE = "mesh_solver_general.py";
const MAX_BRANCHES = 12;
const MAX_BATTERIES = 4;
const PENS = ["m1", "m2", "m3"];
const SIDES = ["top", "bottom", "left", "right"];
const OPPOSITE = { top: "bottom", bottom: "top", left: "right", right: "left" };
const ARROWS = { up: "↑", down: "↓", left: "←", right: "→" };
const TURNS = { clockwise: "↻", "counter-clockwise": "↺" };

const $ = (sel, root = document) => root.querySelector(sel);
const range = (n) => Array.from({ length: n }, (_, i) => i);
const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const minus = (s) => String(s).replace(/^-/, "−");
const sentence = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/* Text from the program uses plain "-" and "I1". Show real minus signs and subscripts. */
function pretty(s) {
  const text = String(s)
    .replace(/(^|[\s(=])-(?=[\dI(])/g, "$1−")
    .replace(/\s-\s/g, " − ");
  return esc(text).replace(/\bI(\d)\b/g, "I<sub>$1</sub>");
}

/* ------------------------------------------------------------------ circuit state */

let nextId = 1;
const mkBranch = (meshes, side, resistance, batteries = []) => ({ id: nextId++, meshes, side, resistance, batteries });
const mkBattery = (volts, plus) => ({ volts, plus });

function worksheetBranches() {
  return [
    mkBranch([0], "left", "", [mkBattery("100", "top")]),
    mkBranch([0], "top", "20"),
    mkBranch([0, 1], "right", "60"),
    mkBranch([1], "top", "40"),
    mkBranch([1], "right", "", [mkBattery("50", "top")]),
  ];
}

const PRESETS = {
  worksheet: () => ({ n: 2, rot: ["cw", "cw", "cw"], branches: worksheetBranches() }),
  flipped: () => ({ n: 2, rot: ["cw", "ccw", "cw"], branches: worksheetBranches() }),
  three: () => ({
    n: 3,
    rot: ["cw", "cw", "cw"],
    branches: [
      mkBranch([0], "left", "", [mkBattery("24", "top")]),
      mkBranch([0], "top", "6"),
      mkBranch([0, 1], "right", "12"),
      mkBranch([1], "top", "4"),
      mkBranch([1, 2], "right", "8", [mkBattery("6", "bottom")]),
      mkBranch([2], "top", "10"),
      mkBranch([2], "right", "", [mkBattery("12", "bottom")]),
    ],
  }),
  blank: () => ({ n: 2, rot: ["cw", "cw", "cw"], branches: [mkBranch([0], "top", "")] }),
};

let state = PRESETS.worksheet();

const plusOptions = (side) => (side === "left" || side === "right" ? ["top", "bottom"] : ["left", "right"]);

function fixPlus(b) {
  const options = plusOptions(b.side);
  b.batteries.forEach((bt) => {
    if (!options.includes(bt.plus)) bt.plus = options[0];
  });
}

/* Choosing meshes for a branch. The lowest-numbered mesh is the one whose side is shown, so when
   that mesh changes the side flips and the branch stays where it was on the drawing. */
function toggleMesh(b, m) {
  const old = b.meshes.slice();
  let next;
  if (old.includes(m)) next = old.length > 1 ? old.filter((x) => x !== m) : old;
  else if (old.length < 2) next = [...old, m];
  else next = [old[0], m];
  next.sort((a, c) => a - c);
  if (next[0] !== old[0]) b.side = OPPOSITE[b.side];
  b.meshes = next;
}

function setMeshCount(n) {
  state.n = n;
  state.branches.forEach((b) => {
    const kept = b.meshes.filter((m) => m < n);
    b.meshes = kept.length ? kept : [0];
  });
}

/* ------------------------------------------------------------------ builder */

function meshPanel() {
  const rows = range(state.n)
    .map(
      (k) => `
    <li class="mesh-row">
      <span class="swatch ${PENS[k]}" aria-hidden="true"></span>
      <span class="mesh-name">Mesh ${k + 1}</span>
      <div class="seg" role="group" aria-label="Direction of the I${k + 1} arrow">
        ${["cw", "ccw"]
          .map(
            (v) => `<button type="button" id="rot-${k}-${v}" data-act="rot" data-k="${k}" data-v="${v}" aria-pressed="${state.rot[k] === v}">${
              v === "cw" ? "↻ Clockwise" : "↺ Counter-clockwise"
            }</button>`
          )
          .join("")}
      </div>
    </li>`
    )
    .join("");
  return `
    <div class="panel">
      <div class="panel-head">
        <h3>Meshes</h3>
        <div class="seg" role="group" aria-label="Number of meshes">
          ${[2, 3]
            .map((n) => `<button type="button" id="n-${n}" data-act="mesh-count" data-n="${n}" aria-pressed="${state.n === n}">${n} meshes</button>`)
            .join("")}
        </div>
      </div>
      <p class="hint">Choose which way each mesh-current arrow turns on your drawing.</p>
      <ul class="mesh-list">${rows}</ul>
    </div>`;
}

function batteryRow(b, bt, q) {
  const options = plusOptions(b.side);
  return `
    <div class="bat">
      <div class="bat-head">
        <label class="lab" for="v-${b.id}-${q}">Battery ${q + 1}</label>
        <button type="button" class="link-btn" id="delbat-${b.id}-${q}" data-act="del-bat" data-b="${b.id}" data-q="${q}" aria-label="Remove battery ${q + 1} from branch ${state.branches.indexOf(b) + 1}">Remove</button>
      </div>
      <div class="bat-controls">
        <span class="input-unit">
          <input id="v-${b.id}-${q}" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="12"
                 value="${esc(bt.volts)}" data-field="volts" data-b="${b.id}" data-q="${q}"><span>V</span>
        </span>
        <div class="seg" role="group" aria-label="Where the + plate of battery ${q + 1} is">
          ${options
            .map(
              (o) => `<button type="button" id="plus-${b.id}-${q}-${o}" data-act="plus" data-b="${b.id}" data-q="${q}" data-v="${o}" aria-pressed="${bt.plus === o}">+ at ${o}</button>`
            )
            .join("")}
        </div>
      </div>
    </div>`;
}

function branchCard(b, i) {
  const chips = range(state.n)
    .map(
      (m) => `<button type="button" id="mesh-${b.id}-${m}" class="chip ${PENS[m]}" data-act="toggle-mesh" data-b="${b.id}" data-m="${m}" aria-pressed="${b.meshes.includes(m)}">Mesh ${m + 1}</button>`
    )
    .join("");
  const sides = SIDES.map(
    (s) => `<button type="button" id="side-${b.id}-${s}" data-act="side" data-b="${b.id}" data-v="${s}" aria-pressed="${b.side === s}">${s}</button>`
  ).join("");
  const shared =
    b.meshes.length === 2
      ? `<p class="hint shared">Shared branch. It is the ${OPPOSITE[b.side]} side of mesh ${b.meshes[1] + 1}.</p>`
      : "";
  return `
    <article class="branch" aria-label="Branch ${i + 1}">
      <div class="b-head">
        <h4>Branch ${i + 1}</h4>
        <button type="button" class="link-btn" id="del-${b.id}" data-act="del-branch" data-b="${b.id}" aria-label="Remove branch ${i + 1}">Remove branch</button>
      </div>
      <div class="row">
        <span class="lab" id="lm-${b.id}">Borders</span>
        <div class="chips" role="group" aria-labelledby="lm-${b.id}">${chips}</div>
      </div>
      <div class="row">
        <span class="lab" id="ls-${b.id}">Side of mesh ${b.meshes[0] + 1}</span>
        <div class="seg" role="group" aria-labelledby="ls-${b.id}">${sides}</div>
      </div>
      ${shared}
      <div class="row">
        <label class="lab" for="r-${b.id}">Resistance</label>
        <span class="input-unit">
          <input id="r-${b.id}" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="0"
                 value="${esc(b.resistance)}" data-field="resistance" data-b="${b.id}"><span>Ω</span>
        </span>
      </div>
      <div class="bats">
        ${b.batteries.map((bt, q) => batteryRow(b, bt, q)).join("")}
        <div><button type="button" class="link-btn" id="addbat-${b.id}" data-act="add-bat" data-b="${b.id}" ${
          b.batteries.length >= MAX_BATTERIES ? "disabled" : ""
        }>Add a battery</button></div>
      </div>
    </article>`;
}

function branchPanel() {
  const cards = state.branches.map(branchCard).join("");
  return `
    <div class="panel">
      <div class="panel-head"><h3>Branches</h3></div>
      <p class="hint">A branch is a stretch of wire between two junctions that holds resistors or batteries. Leave out plain wires. For series resistors type a sum such as 10+22.</p>
      ${cards || '<p class="empty">No branches yet. Add the first one below.</p>'}
      <button type="button" class="btn secondary" id="add-branch" data-act="add-branch" ${
        state.branches.length >= MAX_BRANCHES ? "disabled" : ""
      }>Add branch</button>
    </div>`;
}

function renderBuilder(focusId) {
  $("#builder").innerHTML = meshPanel() + branchPanel();
  if (focusId) {
    const el = document.getElementById(focusId);
    if (el) el.focus();
  }
}

function changed(focusId) {
  renderBuilder(focusId);
  scheduleSolve();
}

const findBranch = (id) => state.branches.find((x) => x.id === Number(id));

$("#builder").addEventListener("click", (e) => {
  const t = e.target.closest("[data-act]");
  if (!t || t.disabled) return;
  const b = findBranch(t.dataset.b);
  let focusId = t.id;
  switch (t.dataset.act) {
    case "mesh-count":
      setMeshCount(Number(t.dataset.n));
      break;
    case "rot":
      state.rot[Number(t.dataset.k)] = t.dataset.v;
      break;
    case "toggle-mesh":
      toggleMesh(b, Number(t.dataset.m));
      break;
    case "side":
      b.side = t.dataset.v;
      fixPlus(b);
      break;
    case "plus":
      b.batteries[Number(t.dataset.q)].plus = t.dataset.v;
      break;
    case "add-bat":
      b.batteries.push(mkBattery("", plusOptions(b.side)[0]));
      focusId = `v-${b.id}-${b.batteries.length - 1}`;
      break;
    case "del-bat":
      b.batteries.splice(Number(t.dataset.q), 1);
      focusId = `addbat-${b.id}`;
      break;
    case "add-branch": {
      const nb = mkBranch([0], "top", "");
      state.branches.push(nb);
      focusId = `r-${nb.id}`;
      break;
    }
    case "del-branch":
      state.branches = state.branches.filter((x) => x !== b);
      focusId = "add-branch";
      break;
    default:
      return;
  }
  changed(focusId);
});

$("#builder").addEventListener("input", (e) => {
  const t = e.target;
  const field = t.dataset && t.dataset.field;
  if (!field) return;
  const b = findBranch(t.dataset.b);
  if (!b) return;
  if (field === "resistance") b.resistance = t.value;
  else if (field === "volts") b.batteries[Number(t.dataset.q)].volts = t.value;
  scheduleSolve();
});

document.querySelectorAll("[data-preset]").forEach((btn) =>
  btn.addEventListener("click", () => {
    state = PRESETS[btn.dataset.preset]();
    changed();
  })
);

/* ------------------------------------------------------------------ share link */

function encodeState() {
  const compact = {
    n: state.n,
    r: state.rot,
    b: state.branches.map((b) => [b.meshes, b.side, b.resistance, b.batteries.map((x) => [x.volts, x.plus])]),
  };
  const bytes = new TextEncoder().encode(JSON.stringify(compact));
  let bin = "";
  bytes.forEach((v) => (bin += String.fromCharCode(v)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeState(text) {
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  const c = JSON.parse(new TextDecoder().decode(bytes));
  const n = c.n === 3 ? 3 : 2;
  const rot = range(3).map((k) => (c.r && c.r[k] === "ccw" ? "ccw" : "cw"));
  const branches = (Array.isArray(c.b) ? c.b : []).slice(0, MAX_BRANCHES).map((row) => {
    const meshes = [...new Set((Array.isArray(row[0]) ? row[0] : []).map(Number).filter((m) => m >= 0 && m < n))]
      .sort((a, c) => a - c)
      .slice(0, 2);
    const side = SIDES.includes(row[1]) ? row[1] : "top";
    const b = mkBranch(meshes.length ? meshes : [0], side, String(row[2] == null ? "" : row[2]).slice(0, 24));
    b.batteries = (Array.isArray(row[3]) ? row[3] : []).slice(0, MAX_BATTERIES).map((x) => mkBattery(String(x[0] == null ? "" : x[0]).slice(0, 24), x[1]));
    fixPlus(b);
    return b;
  });
  return { n, rot, branches };
}

function syncUrl() {
  try {
    history.replaceState(null, "", "#c=" + encodeState());
  } catch (_) {
    /* some browsers refuse this for local files; the link button then copies the plain address */
  }
}

function loadFromUrl() {
  try {
    const m = /^#c=([A-Za-z0-9_-]+)$/.exec(location.hash);
    if (m) state = decodeState(m[1]);
  } catch (_) {
    state = PRESETS.worksheet();
  }
}

async function copyText(text, button, done) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    try {
      ok = document.execCommand("copy");
    } catch (_e) {
      ok = false;
    }
    ta.remove();
  }
  const before = button.textContent;
  button.textContent = ok ? done : "Copy failed";
  setTimeout(() => (button.textContent = before), 1800);
}

$("#copy-link").addEventListener("click", (e) => {
  syncUrl();
  copyText(location.href, e.currentTarget, "Link copied");
});

/* ------------------------------------------------------------------ results */

let lastText = "";

function setStatus(kind, text) {
  const el = $("#py-status");
  el.dataset.state = kind;
  el.textContent = text;
}

function setGlance(html) {
  $("#glance").innerHTML = html;
}

/* body is HTML: callers escape anything that did not come from this file. */
function showMessage(kind, title, body) {
  lastText = "";
  $("#copy-report").disabled = true;
  setGlance(`<span class="g muted">${esc(title)}</span>`);
  $("#live").textContent = kind === "warn" ? title : "";
  $("#results").innerHTML = `<div class="banner ${kind}"><h3>${esc(title)}</h3><p>${body}</p></div>`;
}

function tiles(r) {
  return (
    '<div class="tiles">' +
    r.currents
      .map((c) => {
        const k = c.mesh - 1;
        const real = c.sign === 0 ? "No current" : `${TURNS[c.real_direction] || ""} ${sentence(c.real_direction)}`;
        const note =
          c.sign < 0
            ? `Negative: it really flows ${c.real_direction}, against your arrow.`
            : c.sign > 0
              ? "Flows the way you drew it."
              : "";
        const lines = [c.fraction ? esc(minus(c.fraction)) + " A exactly" : "", esc(real), esc(note)]
          .filter(Boolean)
          .map((t) => `<div class="tile-meta">${t}</div>`)
          .join("");
        return `
        <div class="tile ${PENS[k]}">
          <div class="tile-name">I<sub>${c.mesh}</sub></div>
          <div class="tile-val">${esc(minus(c.decimal))} <span class="u">A</span></div>
          ${lines}
        </div>`;
      })
      .join("") +
    "</div>"
  );
}

function meshCard(m) {
  const k = m.mesh - 1;
  const steps = m.terms
    .map(
      (t) => `
      <li class="${t.kind === "RISE" ? "rise" : "drop"}">
        <div class="sign"><span class="term">${pretty(t.term)}</span><span class="kind">${t.kind === "RISE" ? "Rise" : "Drop"}</span></div>
        <div class="why">
          <div><strong>Branch ${t.branch}</strong> &middot; ${pretty(t.element)}</div>
          <div class="reason">Walking ${esc(t.walking)}: ${pretty(t.why)}</div>
        </div>
      </li>`
    )
    .join("");
  return `
    <article class="mesh-card">
      <h3><span class="swatch ${PENS[k]}" aria-hidden="true"></span>Mesh ${m.mesh}
        <span class="muted">${TURNS[m.rotation] || ""} I<sub>${m.mesh}</sub> turns ${esc(m.rotation)}</span></h3>
      <ol class="walk">${steps}</ol>
      <dl class="sums">
        <dt>Add them up</dt><dd class="eq">${pretty(m.kvl)}</dd>
        <dt>Rearranged</dt><dd class="eq strong">${pretty(m.rearranged)}</dd>
      </dl>
    </article>`;
}

function branchTable(r) {
  const rows = r.branch_currents
    .map(
      (b) => `
      <tr>
        <td>${b.branch}</td>
        <td>${pretty(b.contents)}</td>
        <td class="n">${esc(b.amps)} A</td>
        <td>${b.direction ? ARROWS[b.direction] + " " + esc(b.direction) : "none"}</td>
      </tr>`
    )
    .join("");
  return `
    <div class="block">
      <h3>Real current in every branch</h3>
      <div class="scroll"><table>
        <thead><tr><th>Branch</th><th>On it</th><th class="n">Current</th><th>Flows</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div>`;
}

function checks(r) {
  const kvl = r.kvl_check
    .map((c) => `<li><span class="muted">Mesh ${c.mesh}</span><span class="eq">${esc(c.values.map(minus).join(" ").replace(/^\+/, ""))} = ${esc(c.sum)}</span></li>`)
    .join("");
  const power = r.power.batteries
    .map((p) => `<li><span class="muted">Branch ${p.branch}</span><span>${esc(p.volts)} V battery ${esc(p.verb)} ${esc(p.watts)} W</span></li>`)
    .join("");
  const ok = r.power.balanced;
  return `
    <div class="block">
      <h3>Checks</h3>
      <p class="hint">Each mesh, with the answers put back in, should add up to 0.</p>
      <ul class="check-list">${kvl}</ul>
      <p class="hint">Power from the batteries should equal the heat in the resistors.</p>
      <ul class="check-list">${power}</ul>
      <p><span class="badge ${ok ? "ok" : "bad"}">${ok ? "Balanced" : "Not balanced"}</span>
         Batteries supply ${esc(r.power.source)} W net. Resistors dissipate ${esc(r.power.heat)} W.</p>
    </div>`;
}

function understood(r) {
  const rows = r.understood.branches
    .map((b) => `<tr><td>${b.branch}</td><td>${pretty(b.contents)}</td><td>${esc(b.where)}</td></tr>`)
    .join("");
  const meshes = r.understood.meshes.map((m) => `<li>Mesh ${m.mesh}: ${pretty(m.text)}</li>`).join("");
  return `
    <details class="inline-details">
      <summary>How the program read your inputs</summary>
      <ul class="plain">${meshes}</ul>
      <div class="scroll"><table>
        <thead><tr><th>Branch</th><th>On it</th><th>Where</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </details>`;
}

function renderResults(r) {
  if (!r.ok) {
    showMessage("warn", "Cannot solve yet", esc(sentence(r.error)) + ".");
    return;
  }
  lastText = r.text;
  $("#copy-report").disabled = false;
  setGlance(
    r.currents
      .map((c) => `<span class="g ${PENS[c.mesh - 1]}">I<sub>${c.mesh}</sub> = ${esc(minus(c.decimal))} A</span>`)
      .join("")
  );
  $("#live").textContent =
    "Solved. " +
    r.currents
      .map((c) => `${c.name} is ${c.decimal} amps${c.real_direction ? ", " + c.real_direction : ""}`)
      .join(". ") +
    ".";
  const warnings = (r.warnings || []).map((w) => `<p class="banner warn">${esc(w)}</p>`).join("");
  $("#results").innerHTML =
    warnings +
    tiles(r) +
    r.meshes.map(meshCard).join("") +
    branchTable(r) +
    checks(r) +
    understood(r);
}

$("#copy-report").addEventListener("click", (e) => {
  if (lastText) copyText(lastText, e.currentTarget, "Copied");
});

/* ------------------------------------------------------------------ Python */

let solver = null;
let timer = null;

function payload() {
  return {
    rotations: state.rot.slice(0, state.n),
    branches: state.branches.map((b) => ({
      meshes: b.meshes.map((m) => m + 1),
      side: b.side,
      resistance: b.resistance,
      batteries: b.batteries.map((x) => ({ volts: x.volts, plus: x.plus })),
    })),
  };
}

function solveNow() {
  syncUrl();
  if (!solver) return;
  let r;
  try {
    r = JSON.parse(solver(JSON.stringify(payload())));
  } catch (err) {
    r = { ok: false, error: "the program stopped with an error: " + err.message };
  }
  renderResults(r);
}

function scheduleSolve() {
  clearTimeout(timer);
  timer = setTimeout(solveNow, 80);
}

const STARTUP = `
import sys, types
_module = types.ModuleType("mesh_solver_general")
sys.modules["mesh_solver_general"] = _module
exec(compile(PROGRAM_SOURCE, "mesh_solver_general.py", "exec"), _module.__dict__)
solve_web = _module.solve_web
sys.version.split()[0]
`;

/* An error whose message is HTML written in this file, so it is shown as it is. */
function trusted(html) {
  const err = new Error(html);
  err.trustedHtml = true;
  return err;
}

async function boot() {
  showMessage("warn", "Python is starting", "Your circuit is solved as soon as it is ready. This takes a few seconds the first time.");
  try {
    let source;
    try {
      const res = await fetch(PROGRAM_FILE);
      if (!res.ok) throw new Error("status " + res.status);
      source = await res.text();
    } catch (err) {
      const help =
        location.protocol === "file:"
          ? "This page was opened straight from a folder, which browsers do not allow. Run <code>python3 -m http.server</code> in the folder and open <code>http://localhost:8000</code>."
          : "Check that the file is in the same folder as index.html.";
      throw trusted(`Could not read <code>${PROGRAM_FILE}</code> (${esc(err.message)}). ${help}`);
    }
    $("#source-code").textContent = source;

    if (typeof loadPyodide !== "function") {
      throw trusted("The Pyodide script did not load. Check your internet connection and reload the page.");
    }
    const py = await loadPyodide({ indexURL: PYODIDE_URL });
    py.globals.set("PROGRAM_SOURCE", source);
    const version = py.runPython(STARTUP);
    solver = py.globals.get("solve_web");
    setStatus("ready", "Python " + version + " ready");
    solveNow();
  } catch (err) {
    setStatus("error", "Python did not start");
    showMessage("error", "Python did not start", err.trustedHtml ? err.message : esc(err.message));
  }
}

loadFromUrl();
renderBuilder();
boot();
