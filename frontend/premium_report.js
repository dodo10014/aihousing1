// ===========================
// AiHousing – FINAL VERSION
// ===========================

const API_BASE = "http://127.0.0.1:8000";

// ===========================
// UTILS
// ===========================

function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }
function setHTML(id, val) { const el = document.getElementById(id); if (el) el.innerHTML = val; }
function hide(el) { if (typeof el === "string") el = qs(el); if (el) el.style.display = "none"; }
function show(el) { if (typeof el === "string") el = qs(el); if (el) el.style.display = "block"; }

// ===========================
// SKELETON LOADING
// ===========================

function activateSkeleton() {
  qsa(".summary-card, .side-panel, .card").forEach((el) => {
    el.classList.add("skeleton-rect");
  });
}

function disableSkeleton() {
  qsa(".summary-card, .side-panel, .card").forEach((el) => {
    el.classList.remove("skeleton-rect");
  });
}

// ===========================
// MAIN LOAD
// ===========================

async function loadReport() {
  const urlParams = new URLSearchParams(window.location.search);
  const sessionId = urlParams.get("session_id");

  if (!sessionId) {
    setHTML("error", "Missing session ID.");
    show("#error");
  }

  activateSkeleton();
  hide("#error");
  show("#loading");
  setHTML("loading", "Loading your AI report…");

  try {
    const res = await fetch(`${API_BASE}/premium-report?session_id=${sessionId}`);
    if (!res.ok) throw new Error("Failed");

    const data = await res.json();
    window.__aihousingReport = data;

    disableSkeleton();
    hide("#loading");

    fillReport(data);

  } catch (err) {
    setHTML("error", "Could not load report. Try again.");
    hide("#loading");
    show("#error");
  }
}

// ===========================
// REPORT FILL
// ===========================

function fillReport(data) {
  const ai = data.ai || {};

  // TITLE
  setHTML("report-title", ai.title || "AI property report");
  setHTML("summary-tagline", ai.subtitle || "AI-generated property summary.");

  // DATE + ID
  const now = new Date();
  const nice = now.toLocaleDateString("en-UK", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  setHTML(
    "report-sub",
    `Generated: <strong>${nice}</strong> · Report ID: <strong>#${data.session_id}</strong>`
  );

  // SUMMARY
  setHTML("overall-score", ai.overall_condition_score || "–");
  setHTML("overall-condition-label", ai.overall_condition_label || "–");
  setHTML("summary-max-offer", ai.max_recommended_offer || "–");
  setHTML("summary-ai-range", ai.ai_value_range || "–");
  setHTML("summary-damp", ai.damp_mould_risk || "–");
  setHTML("summary-crime", ai.crime_noise || "–");
  setHTML("summary-flood", ai.flood_zone || "–");

  // TAGS
  const tags = ai.tags || [];
  setHTML(
    "summary-tags",
    tags.map((t) => `<div class="tag">${t}</div>`).join("")
  );

  // SIDE PANEL
  setHTML("side-main", ai.subtitle || "");
  setHTML("side-chip", `<div class="risk-dot"></div>${ai.overall_condition_label || ""}`);

  setHTML(
    "side-list",
    (ai.section1_points || []).map((x) => `<li>${x}</li>`).join("")
  );

  // KEY POINTS
  setHTML(
    "section1-bullets",
    (ai.section1_points || []).map(
      (b) => `
        <span>
          <div class="summary-icon">•</div>
          <div>${b}</div>
        </span>`
    ).join("")
  );

  // PHOTOS
  if (ai.photo_analysis) {
    const html = ai.photo_analysis
      .map(
        (p) => `
      <div class="photo-card">
        <img src="${p.base64}" />
        <div class="photo-body">
          <div class="photo-label">AI photo analysis</div>
          <div class="photo-title">${p.title}</div>
          <div>${p.description}</div>
          <div class="photo-tag-row">
            ${p.tags.map((t) => `<div class="photo-tag">${t}</div>`).join("")}
          </div>
        </div>
      </div>`
      )
      .join("");

    setHTML("photos-grid", html);
  }

  // NEGOTIATION
  setHTML("neg-list", (ai.negotiation_bullets || []).map((x) => `<li>${x}</li>`).join(""));
  setHTML("negText", ai.negotiation_email || "");

  // NEXT STEPS
  setHTML("next-steps", (ai.next_steps || []).map((x) => `<li>${x}</li>`).join(""));

  // RAW
  setHTML("raw-report", ai.raw_full_report || "");
}

// ===========================
// INIT
// ===========================

document.addEventListener("DOMContentLoaded", loadReport);
