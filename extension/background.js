// Laura Companion — Background Service Worker
// Polls Laura API periodically and shows notifications

const LAURA_API = "http://127.0.0.1:8888";
const POLL_INTERVAL_MIN = 1;

let lastStatus = null;
let notifiedOrders = new Set();

// Load saved server URL
chrome.storage.sync.get("lauraUrl", (data) => {
  if (data.lauraUrl) {
    // Custom URL set by user
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("pollLaura", { periodInMinutes: POLL_INTERVAL_MIN });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "pollLaura") {
    pollStatus();
  }
});

async function pollStatus() {
  try {
    const [statusResp, metricsResp, healthResp] = await Promise.all([
      fetch(`${LAURA_API}/api/status`).then((r) => r.json()).catch(() => null),
      fetch(`${LAURA_API}/api/dashboard/metrics`).then((r) => r.json()).catch(() => null),
      fetch(`${LAURA_API}/api/health`).then((r) => r.json()).catch(() => null),
    ]);

    const status = {
      running: statusResp?.running ?? false,
      health: healthResp ?? null,
      metrics: metricsResp ?? null,
      timestamp: Date.now(),
    };

    lastStatus = status;
    chrome.storage.local.set({ lastStatus: status });

    // Update badge
    const healthScore = status.health?.health_score ?? 0;
    const badgeColor = healthScore >= 80 ? "#22c55e" : healthScore >= 50 ? "#f59e0b" : "#ef4444";
    chrome.action.setBadgeText({ text: healthScore > 0 ? `${healthScore}` : "?" });
    chrome.action.setBadgeBackgroundColor({ color: badgeColor });

    // Check for notifications
    if (statusResp?.pending_approvals > 0) {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: "Laura — Aprovações Pendentes",
        message: `${statusResp.pending_approvals} itens aguardando aprovação`,
        priority: 1,
      });
    }
  } catch (err) {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#6b7280" });
  }
}

// Listen for popup requests
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "getStatus") {
    sendResponse(lastStatus);
  }
  if (request.type === "setUrl") {
    chrome.storage.sync.set({ lauraUrl: request.url });
  }
});
