// success.js

// 🔧 CONFIG – la fel ca în paywall.js:
const API_BASE = "http://localhost:8000"; // sau "https://domeniul-tau.ro"

document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("success-status");
  if (!statusEl) {
    console.error('Nu există element cu id="success-status" în success.html');
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("session_id");

  if (!sessionId) {
    statusEl.textContent = "Missing session_id in URL.";
    return;
  }

  statusEl.textContent = "Checking payment status...";

  checkPaymentStatus(sessionId, statusEl);
});

async function checkPaymentStatus(sessionId, statusEl) {
  try {
    const res = await fetch(`${API_BASE}/checkout-session?session_id=${encodeURIComponent(sessionId)}`);
    const data = await res.json();

    if (!res.ok) {
      const msg = data.detail || JSON.stringify(data);
      throw new Error(msg);
    }

    if (data.payment_status === "paid") {
      statusEl.innerHTML = `
        <h2>Payment successful ✅</h2>
        <p>Your report is ready.</p>
        <a href="premium_report.html?session_id=${encodeURIComponent(sessionId)}">
          View your premium report
        </a>
      `;
    } else {
      statusEl.innerHTML = `
        <h2>Payment not completed ❌</h2>
        <p>Status: ${data.payment_status}</p>
        <p>If money was taken from your card, wait a bit and refresh this page.</p>
      `;
    }
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error: " + err.message;
  }
}
