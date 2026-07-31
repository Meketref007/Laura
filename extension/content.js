// Laura Companion — Content Script for Seller Center
// Injects quick actions and status into Shopee Seller Center pages

(function () {
  "use strict";

  const API = "http://127.0.0.1:8888";

  // Only run on Seller Center pages
  if (!window.location.hostname.includes("seller.shopee.com.br")) return;

  // Wait for page to load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inject);
  } else {
    inject();
  }

  function inject() {
    // Add a Laura status bar at the top of Seller Center
    const bar = document.createElement("div");
    bar.id = "laura-status-bar";
    bar.style.cssText = `
      background: #0f172a; color: #e2e8f0; padding: 6px 16px;
      font-size: 12px; display: flex; align-items: center; gap: 16px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      border-bottom: 1px solid #1e293b; z-index: 9999; position: relative;
    `;
    bar.innerHTML = `
      <span style="font-weight:700;color:#3b82f6;">Laura</span>
      <span id="laura-health" style="color:#6b7280;">conectando...</span>
      <span id="laura-orders" style="color:#6b7280;"></span>
      <span id="laura-stock" style="color:#6b7280;"></span>
      <span style="margin-left:auto;">
        <a href="http://127.0.0.1:8888" target="_blank"
           style="color:#3b82f6;text-decoration:none;">Dashboard</a>
      </span>
    `;

    const target = document.querySelector("header") || document.body;
    target.parentNode?.insertBefore(bar, target);

    fetchStatus();
    setInterval(fetchStatus, 30000);
  }

  async function fetchStatus() {
    try {
      const resp = await fetch(`${API}/api/status`);
      const data = await resp.json();

      const health = document.getElementById("laura-health");
      if (health) {
        const score = data.health?.health_score ?? 0;
        health.textContent = `Saúde: ${score}/100`;
        health.style.color = score >= 80 ? "#22c55e" : score >= 50 ? "#f59e0b" : "#ef4444";
      }

      const orders = document.getElementById("laura-orders");
      if (orders && data.pending_orders !== undefined) {
        orders.textContent = `📦 ${data.pending_orders} pedidos`;
      }

      const stock = document.getElementById("laura-stock");
      if (stock && data.low_stock !== undefined) {
        stock.textContent = `⚠️ ${data.low_stock} itens baixo estoque`;
      }
    } catch (err) {
      const health = document.getElementById("laura-health");
      if (health) {
        health.textContent = "offline";
        health.style.color = "#6b7280";
      }
    }
  }
})();
