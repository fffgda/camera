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

const currentCountEl = document.getElementById("currentCount");
const maxCountEl = document.getElementById("maxCount");
const totalSessionEl = document.getElementById("totalSession");
const alertCountEl = document.getElementById("alertCount");
const alertsListEl = document.getElementById("alertsList");

let isAdmin = false;
let maxCountToday = 0;
let totalAlerts = 0;

// =========================
// CHART
// =========================
const chartCtx = document.getElementById("peopleChart").getContext("2d");
const maxDataPoints = 60;
const chartLabels = [];
const chartData = [];

const peopleChart = new Chart(chartCtx, {
  type: "line",
  data: {
    labels: chartLabels,
    datasets: [{
      label: "Personnes",
      data: chartData,
      borderColor: "#60a5fa",
      backgroundColor: "rgba(96, 165, 250, 0.1)",
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: {
        display: true,
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: "#94a3b8", maxTicksLimit: 10 },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: "#94a3b8", stepSize: 1 },
      },
    },
    plugins: {
      legend: { display: false },
    },
  },
});

function addChartPoint(count) {
  const now = new Date();
  const label = now.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  chartLabels.push(label);
  chartData.push(count);

  if (chartLabels.length > maxDataPoints) {
    chartLabels.shift();
    chartData.shift();
  }

  peopleChart.update();
}

// =========================
// OVERLAY
// =========================
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
    ctx.fillText(`Person ${i + 1}`, x + 6, y - 6);
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
    setTimeout(pollFaces, 500);
  }
}

// =========================
// PEOPLE COUNT
// =========================
async function pollPeople() {
  try {
    const res = await fetch("/api/people");
    if (!res.ok) return;
    const data = await res.json();

    const count = data.count || 0;
    currentCountEl.textContent = count;
    totalSessionEl.textContent = data.total_session || 0;

    if (count > maxCountToday) {
      maxCountToday = count;
      maxCountEl.textContent = maxCountToday;
    }

    addChartPoint(count);
  } catch (e) {
    // silent
  } finally {
    setTimeout(pollPeople, 2000);
  }
}

async function pollAlerts() {
  try {
    const res = await fetch("/api/alerts?limit=10");
    if (!res.ok) return;
    const data = await res.json();

    totalAlerts = data.length;
    alertCountEl.textContent = totalAlerts;

    if (data.length === 0) {
      alertsListEl.innerHTML = '<p class="hint">Aucune alerte pour le moment.</p>';
    } else {
      alertsListEl.innerHTML = data.map((a) => {
        const d = new Date(a.timestamp * 1000);
        const timeStr = d.toLocaleString("fr-FR");
        return `<div class="alert-item">
          <span class="alert-time">${timeStr}</span>
          <span class="alert-msg">${a.message}</span>
          <span class="alert-count">${a.count} pers.</span>
        </div>`;
      }).join("");
    }
  } catch (e) {
    // silent
  } finally {
    setTimeout(pollAlerts, 5000);
  }
}

// =========================
// API
// =========================
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
  pollPeople();
  pollAlerts();
  refresh();
  setInterval(refresh, 1500);
})();
