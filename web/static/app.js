const modePill = document.getElementById("modePill");
const posPill = document.getElementById("posPill");
const stepInput = document.getElementById("step");

const manualBtn = document.getElementById("manualBtn");
const autoBtn = document.getElementById("autoBtn");
const centerBtn = document.getElementById("centerBtn");

const cam = document.getElementById("cam");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");

function resizeCanvasToImage() {
  // taille affichée
  const rect = cam.getBoundingClientRect();
  overlay.width = Math.round(rect.width);
  overlay.height = Math.round(rect.height);
}

window.addEventListener("resize", resizeCanvasToImage);
cam.addEventListener("load", resizeCanvasToImage);

function drawFaces(data) {
  // data.frame_w / frame_h = taille originale de la frame OpenCV
  if (!data || !data.frame_w || !data.frame_h) return;

  // Clear
  ctx.clearRect(0, 0, overlay.width, overlay.height);

  const sx = overlay.width / data.frame_w;
  const sy = overlay.height / data.frame_h;

  ctx.lineWidth = 3;
  ctx.strokeStyle = "lime";
  ctx.font = "14px system-ui";
  ctx.fillStyle = "lime";

  (data.faces || []).forEach((f, i) => {
    const x = f.x * sx;
    const y = f.y * sy;
    const w = f.w * sx;
    const h = f.h * sy;
    ctx.strokeRect(x, y, w, h);
    ctx.fillText(`Face ${i+1}`, x + 6, y - 6);
  });
}

async function pollFaces() {
  try {
    const res = await fetch("/api/faces");
    const data = await res.json();
    drawFaces(data);
  } catch (e) {
    // si erreur, efface
    ctx.clearRect(0, 0, overlay.width, overlay.height);
  } finally {
    setTimeout(pollFaces, 120); // ~8fps overlay
  }
}

resizeCanvasToImage();
pollFaces();

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `HTTP ${res.status}`);
  }
  return res.json();
}

async function refresh() {
  const res = await fetch("/api/state");
  const s = await res.json();
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

async function setMode(mode) {
  const s = await api("/api/mode", { mode });
  modePill.textContent = `Mode: ${s.mode}`;
}

async function move(dir) {
  const step = parseInt(stepInput.value || "2", 10);
  const s = await api("/api/move", { dir, step });
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

async function center() {
  const s = await api("/api/center");
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

// Auto-repeat (maintenir appuyé)
let timer = null;
function startRepeat(dir) {
  move(dir);
  timer = setInterval(() => move(dir), 120);
}
function stopRepeat() {
  if (timer) clearInterval(timer);
  timer = null;
}

document.querySelectorAll(".btn[data-dir]").forEach(btn => {
  const dir = btn.dataset.dir;

  btn.addEventListener("mousedown", () => startRepeat(dir));
  btn.addEventListener("mouseup", stopRepeat);
  btn.addEventListener("mouseleave", stopRepeat);

  // mobile
  btn.addEventListener("touchstart", (e) => { e.preventDefault(); startRepeat(dir); }, { passive:false });
  btn.addEventListener("touchend", stopRepeat);
});

manualBtn.addEventListener("click", () => setMode("manual"));
autoBtn.addEventListener("click", () => setMode("auto"));
centerBtn.addEventListener("click", center);

refresh();
setInterval(refresh, 1500);
