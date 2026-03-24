const modePill = document.getElementById("modePill");
const posPill = document.getElementById("posPill");
const stepInput = document.getElementById("step");

const manualBtn = document.getElementById("manualBtn");
const autoBtn = document.getElementById("autoBtn");
const centerBtn = document.getElementById("centerBtn");
const logoutBtn = document.getElementById("logoutBtn");
const userPill = document.getElementById("userPill");
const viewerNotice = document.getElementById("viewerNotice");

const cam = document.getElementById("cam");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");

let isAdmin = false;

function resizeCanvasToImage() {
  const rect = cam.getBoundingClientRect();
  overlay.width = Math.round(rect.width);
  overlay.height = Math.round(rect.height);
}

window.addEventListener("resize", resizeCanvasToImage);
cam.addEventListener("load", resizeCanvasToImage);

function drawFaces(data) {
  if (!data || !data.frame_w || !data.frame_h) return;

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
    ctx.fillText(`Face ${i + 1}`, x + 6, y - 6);
  });
}

async function pollFaces() {
  try {
    const res = await fetch("/api/faces");
    if (!res.ok) return;
    const data = await res.json();
    drawFaces(data);
  } catch (e) {
    ctx.clearRect(0, 0, overlay.width, overlay.height);
  } finally {
    setTimeout(pollFaces, 120);
  }
}

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

function setAdminUI(enabled) {
  document.querySelectorAll(".admin-only").forEach((el) => {
    if ("disabled" in el) {
      el.disabled = !enabled;
    }
    el.classList.toggle("disabled", !enabled);
  });

  viewerNotice.classList.toggle("hidden", enabled);
}

async function loadUser() {
  const res = await fetch("/api/me");
  const me = await res.json();

  if (!me.authenticated) {
    window.location.href = "/login";
    return;
  }

  isAdmin = me.user.role === "admin";
  userPill.textContent = `Utilisateur: ${me.user.username} (${me.user.role})`;
  setAdminUI(isAdmin);
}

async function refresh() {
  const res = await fetch("/api/state");
  if (!res.ok) return;
  const s = await res.json();
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

async function setMode(mode) {
  if (!isAdmin) return;
  const s = await api("/api/mode", { mode });
  modePill.textContent = `Mode: ${s.mode}`;
}

async function move(dir) {
  if (!isAdmin) return;
  const step = parseInt(stepInput.value || "2", 10);
  const s = await api("/api/move", { dir, step });
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

async function center() {
  if (!isAdmin) return;
  const s = await api("/api/center");
  modePill.textContent = `Mode: ${s.mode}`;
  posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
}

let timer = null;
function startRepeat(dir) {
  if (!isAdmin) return;
  move(dir);
  timer = setInterval(() => move(dir), 120);
}

function stopRepeat() {
  if (timer) clearInterval(timer);
  timer = null;
}

document.querySelectorAll(".btn[data-dir]").forEach((btn) => {
  const dir = btn.dataset.dir;

  btn.addEventListener("mousedown", () => startRepeat(dir));
  btn.addEventListener("mouseup", stopRepeat);
  btn.addEventListener("mouseleave", stopRepeat);

  btn.addEventListener(
    "touchstart",
    (e) => {
      e.preventDefault();
      startRepeat(dir);
    },
    { passive: false }
  );
  btn.addEventListener("touchend", stopRepeat);
});

manualBtn?.addEventListener("click", () => setMode("manual"));
autoBtn?.addEventListener("click", () => setMode("auto"));
centerBtn?.addEventListener("click", center);
logoutBtn?.addEventListener("click", async () => {
  await api("/api/logout", {});
  window.location.href = "/login";
});

(async function init() {
  resizeCanvasToImage();
  await loadUser();
  pollFaces();
  refresh();
  setInterval(refresh, 1500);
})();
