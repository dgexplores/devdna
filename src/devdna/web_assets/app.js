/* DevDNA progressive enhancement: live pending-page polling and scroll reveals.
 * Everything here is optional; pages remain fully usable without JavaScript. */
(function () {
  "use strict";

  var reducedMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Pending page: live status polling ---------- */

  var POLL_INTERVAL_MS = 2500;
  var REQUEST_TIMEOUT_MS = 8000;
  var MAX_CONSECUTIVE_FAILURES = 3;
  var MAX_TOTAL_WAIT_MS = 5 * 60 * 1000;

  var STAGE_COPY = {
    queued: "Queued — waiting for a worker slot.",
    running: "Inspecting public repositories and matching evidence.",
    completed: "Evidence verified. Opening your report.",
    partial: "Collected with warnings. Opening your report.",
    failed: "This analysis failed.",
  };

  function pendingPanel() {
    return document.querySelector("[data-poll-url]");
  }

  function setText(el, text) {
    if (el && el.textContent !== text) el.textContent = text;
  }

  function pollOnce(panel) {
    var controller = new AbortController();
    var timer = window.setTimeout(function () {
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    return window
      .fetch(panel.getAttribute("data-poll-url"), {
        signal: controller.signal,
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .finally(function () {
        window.clearTimeout(timer);
      });
  }

  function finishAnalysis(panel, reportUrl) {
    var target = reportUrl || window.location.pathname;
    panel.setAttribute("data-state", "leaving");
    setText(
      document.querySelector("[data-pending-note]"),
      "You will be redirected automatically. If nothing happens, open the report.",
    );
    var delay = reducedMotion ? 0 : 550;
    window.setTimeout(function () {
      if (panel.hasAttribute("data-reload-on-ready")) {
        window.location.reload();
      } else {
        window.location.href = target;
      }
    }, delay);
  }

  function failAnalysis(panel, message) {
    panel.setAttribute("data-state", "failed");
    panel.removeAttribute("aria-busy");
    var note = document.querySelector("[data-pending-note]");
    setText(note, message || "The worker reported a failure for this analysis.");
  }

  function stallAnalysis(panel) {
    if (panel.getAttribute("data-state") === "failed") return;
    panel.setAttribute("data-state", "stalled");
    setText(
      document.querySelector("[data-pending-note]"),
      "Connection to the analysis API is unstable. Still trying — or reload this page.",
    );
  }

  function recoverStall(panel) {
    if (panel.getAttribute("data-state") === "stalled") {
      panel.setAttribute("data-state", "active");
      setText(document.querySelector("[data-pending-note]"), "");
    }
  }

  function startPolling() {
    var panel = pendingPanel();
    if (!panel) return;
    var reportUrl = panel.getAttribute("data-report-url");

    var statusEl = document.querySelector("[data-pending-status]");
    var stageEl = document.querySelector("[data-pending-stage]");
    var startedAt = Date.now();
    var consecutiveFailures = 0;

    function batchReady(data) {
      if (!data || !Array.isArray(data.candidates)) return true;
      return !data.candidates.some(function (candidate) {
        return candidate && (candidate.status === "queued" || candidate.status === "running");
      });
    }

    function applyPayload(data) {
      if (data && typeof data.status === "string") {
        var status = data.status;
        var errorMessage = data.error_message ? String(data.error_message) : "";
        panel.setAttribute("data-status", status);
        if (status === "completed" || status === "partial") {
          setText(statusEl, status.charAt(0).toUpperCase() + status.slice(1));
          setText(stageEl, STAGE_COPY[status] || STAGE_COPY.completed);
          finishAnalysis(panel, reportUrl);
          return true;
        }
        if (status === "failed") {
          failAnalysis(panel, errorMessage);
          return true;
        }
        setText(statusEl, status.charAt(0).toUpperCase() + status.slice(1));
        setText(stageEl, STAGE_COPY[status] || STAGE_COPY.running);
        return false;
      }
      if (batchReady(data)) {
        finishAnalysis(panel, reportUrl);
        return true;
      }
      setText(stageEl, "Comparing candidate evidence. This page updates itself.");
      return false;
    }

    function tick() {
      pollOnce(panel).then(
        function (data) {
          consecutiveFailures = 0;
          recoverStall(panel);
          var done = applyPayload(data);
          if (!done) window.setTimeout(tick, POLL_INTERVAL_MS);
        },
        function () {
          consecutiveFailures += 1;
          if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) stallAnalysis(panel);
          if (Date.now() - startedAt >= MAX_TOTAL_WAIT_MS) {
            failAnalysis(
              panel,
              "This is taking unusually long. Reload the page to check the latest state.",
            );
            return;
          }
          window.setTimeout(tick, Math.min(POLL_INTERVAL_MS * consecutiveFailures, 10000));
        },
      );
    }

    var initialStatus = panel.getAttribute("data-initial-status") || "";
    if (initialStatus && !applyPayload({ status: initialStatus })) tick();
  }

  /* ---------- Copy-to-clipboard buttons ---------- */

  function initCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy-target]");
    if (!buttons.length) return;
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var selector = button.getAttribute("data-copy-target");
        var source = selector ? document.getElementById(selector) : null;
        var text = source && "value" in source ? String(source.value) : "";
        if (!text) return;
        var markCopied = function () {
          button.classList.add("copied");
          var original = button.textContent;
          button.textContent = "Copied";
          window.setTimeout(function () {
            button.classList.remove("copied");
            button.textContent = original;
          }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(markCopied, function () {});
        } else {
          source.select();
          document.execCommand("copy");
          markCopied();
        }
      });
    });
  }

  /* ---------- Scroll reveals ---------- */

  var REVEAL_SELECTOR = [
    ".feature-card",
    ".home-workflow li",
    ".context-block",
    ".learning-item",
    ".candidate-row",
  ].join(", ");

  function startReveals() {
    if (reducedMotion || !("IntersectionObserver" in window)) return;
    var targets = document.querySelectorAll(REVEAL_SELECTOR);
    if (!targets.length) return;
    document.documentElement.classList.add("reveal-ready");
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    targets.forEach(function (target, index) {
      target.classList.add("reveal-item");
      target.style.setProperty("--reveal-delay", Math.min(index % 6, 4) * 60 + "ms");
      observer.observe(target);
    });
  }

  function init() {
    try {
      startPolling();
    } catch (error) {
      /* Polling must never break the page. */
    }
    try {
      initCopyButtons();
    } catch (error) {
      /* Copy buttons are optional. */
    }
    try {
      startReveals();
    } catch (error) {
      /* Reveals are cosmetic only. */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
