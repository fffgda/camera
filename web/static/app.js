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

const posNameInput = document.getElementById("posName");
const savePosBtn = document.getElementById("savePosBtn");
const positionsListEl = document.getElementById("positionsList");

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

// =========================
// SSE (Server-Sent Events)
// =========================
function initSSE() {
  const evtSource = new EventSource("/api/events");

  evtSource.addEventListener("faces", (e) => {
    try {
      const data = JSON.parse(e.data);
      drawFaces(data);
    } catch (err) {
      // silent
    }
  });

  evtSource.addEventListener("people", (e) => {
    try {
      const data = JSON.parse(e.data);
      const count = data.count || 0;
      currentCountEl.textContent = count;
      totalSessionEl.textContent = data.total_session || 0;

      if (count > maxCountToday) {
        maxCountToday = count;
        maxCountEl.textContent = maxCountToday;
      }

      addChartPoint(count);
    } catch (err) {
      // silent
    }
  });

  evtSource.addEventListener("motion", (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.motion) {
        console.log("[SSE] Mouvement détecté");
      }
    } catch (err) {
      // silent
    }
  });

  // Mise à jour immédiate des alertes dès réception via SSE
  evtSource.addEventListener("alert", (e) => {
    try {
      pollAlerts();
    } catch (err) {
      // silent
    }
  });

  evtSource.onerror = () => {
    console.log("[SSE] Déconnecté, reconnexion automatique...");
  };

  return evtSource;
}

// =========================
// HISTORIQUE (chargé une fois au démarrage)
// =========================
async function loadHistory() {
  try {
    const res = await fetch("/api/people/history?limit=60");
    if (!res.ok) return;
    const data = await res.json();

    // L'API renvoie du plus récent au plus ancien, on inverse pour le graphique
    const sorted = data.slice().reverse();

    sorted.forEach((item) => {
      const d = new Date(item.timestamp * 1000);
      const label = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      chartLabels.push(label);
      chartData.push(item.count);

      if (item.count > maxCountToday) {
        maxCountToday = item.count;
      }
    });

    // Mettre à jour les stats affichées
    if (sorted.length > 0) {
      const latest = sorted[sorted.length - 1];
      currentCountEl.textContent = latest.count;
      totalSessionEl.textContent = latest.total || 0;
      maxCountEl.textContent = maxCountToday;
    }

    peopleChart.update();
    console.log(`[HISTORY] ${sorted.length} points chargés depuis la base`);
  } catch (e) {
    console.error("[HISTORY] Erreur chargement historique:", e);
  }
}

// =========================
// ALERTS (polling 10s)
// =========================
function renderAlerts(data) {
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
}

async function pollAlerts() {
  try {
    const res = await fetch("/api/alerts?limit=10");
    if (!res.ok) return;
    const data = await res.json();
    renderAlerts(data);
  } catch (e) {
    // silent
  } finally {
    setTimeout(pollAlerts, 10000);
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

// =========================
// POSITIONS
// =========================
function renderPositions(positions) {
  if (!positions || positions.length === 0) {
    positionsListEl.innerHTML = '<p class="hint">Aucune position sauvegardée.</p>';
    return;
  }

  positionsListEl.innerHTML = positions.map((p) => {
    const deleteBtn = isAdmin
      ? `<button class="small pos-delete" data-id="${p.id}" title="Supprimer">✕</button>`
      : '';
    return `<div class="position-item">
      <button class="pos-btn" data-id="${p.id}" title="Pan: ${p.pan} | Tilt: ${p.tilt}">
        <span class="pos-name">${p.name}</span>
        <span class="pos-angles">P:${p.pan} T:${p.tilt}</span>
      </button>
      ${deleteBtn}
    </div>`;
  }).join("");

  positionsListEl.querySelectorAll(".pos-btn").forEach((btn) => {
    btn.addEventListener("click", () => recallPosition(parseInt(btn.dataset.id, 10)));
  });

  positionsListEl.querySelectorAll(".pos-delete").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deletePosition(parseInt(btn.dataset.id, 10));
    });
  });
}

async function loadPositions() {
  try {
    const res = await fetch("/api/positions");
    if (!res.ok) return;
    const positions = await res.json();
    renderPositions(positions);
  } catch (e) {
    // silent
  }
}

async function savePosition() {
  if (!isAdmin) return;
  const name = posNameInput.value.trim();
  if (!name) return;

  try {
    const stateRes = await fetch("/api/state");
    const s = await stateRes.json();
    await api("/api/positions", { name, pan: s.pan, tilt: s.tilt });
    posNameInput.value = "";
    loadPositions();
  } catch (e) {
    console.error("Erreur sauvegarde position:", e);
  }
}

async function recallPosition(id) {
  if (!isAdmin) return;
  try {
    const s = await api("/api/positions/recall", { id });
    modePill.textContent = `Mode: ${s.mode}`;
    posPill.textContent = `Pan: ${s.pan} | Tilt: ${s.tilt}`;
  } catch (e) {
    console.error("Erreur rappel position:", e);
  }
}

async function deletePosition(id) {
  if (!isAdmin) return;
  try {
    await fetch(`/api/positions/${id}`, { method: "DELETE" });
    loadPositions();
  } catch (e) {
    console.error("Erreur suppression position:", e);
  }
}

savePosBtn?.addEventListener("click", savePosition);

(async function init() {
  resizeCanvasToImage();
  await loadUser();
  await loadHistory();  // Charger l'historique avant de démarrer le SSE
  initSSE();
  pollAlerts();
  loadPositions();
  refresh();
  setInterval(refresh, 3000);
})();
