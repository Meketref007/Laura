// Laura Companion — Popup Script
// Displays real-time status from the Laura agent API

const API = "http://127.0.0.1:8888";

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  fetchData();
  document.getElementById("refresh-btn").addEventListener("click", fetchData);
  document.getElementById("save-url").addEventListener("click", saveUrl);
});

async function fetchData() {
  try {
    const [status, metrics, health] = await Promise.all([
      fetch(`${API}/api/status`).then((r) => r.json()).catch(() => null),
      fetch(`${API}/api/dashboard/metrics`).then((r) => r.json()).catch(() => null),
      fetch(`${API}/api/health`).then((r) => r.json()).catch(() => null),
    ]);

    // Health score
    const score = health?.health_score ?? 0;
    setText("health-score", score > 0 ? `${score}/100` : "--");
    setText("cycle-count", status?.cycle_count ?? "--");
    setText("error-count", status?.error_count ?? "--");

    // Status badge
    const badge = document.getElementById("badge-status");
    if (status?.running) {
      badge.textContent = "online";
      badge.className = "badge online";
    } else {
      badge.textContent = "offline";
      badge.className = "badge offline";
    }

    // Skills metrics
    if (metrics?.skills) {
      setText("skills-total", metrics.skills.total ?? "--");
      setText("skills-ok", metrics.skills.ok ?? "--");
      setText("skills-fail", metrics.skills.fail ?? "--");
    }

    // Plan success rate
    if (metrics?.plans) {
      const total = metrics.plans.total || 1;
      const ok = metrics.plans.ok || 0;
      const pct = Math.round((ok / total) * 100);
      document.getElementById("plan-success-bar").style.width = `${pct}%`;
      setText("plan-ratio", `${ok}/${total} (${pct}%)`);
    }

    // Last cycle
    if (status?.last_cycle) {
      setText("last-cycle", new Date(status.last_cycle).toLocaleString("pt-BR"));
    }
  } catch (err) {
    console.error("Laura fetch error:", err);
    document.getElementById("badge-status").textContent = "offline";
    document.getElementById("badge-status").className = "badge offline";
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function loadConfig() {
  chrome.storage.sync.get("lauraUrl", (data) => {
    if (data.lauraUrl) {
      document.getElementById("server-url").value = data.lauraUrl;
    }
  });
}

function saveUrl() {
  const url = document.getElementById("server-url").value.trim();
  chrome.storage.sync.set({ lauraUrl: url }, () => {
    const btn = document.getElementById("save-url");
    btn.textContent = "✓ Salvo";
    setTimeout(() => { btn.textContent = "Salvar"; }, 1500);
  });
}
