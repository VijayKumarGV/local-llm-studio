/**
 * Error-recovery helpers.
 *
 *   showBanner({message, tone, actions})   render/replace a persistent banner
 *   dismissBanner()                        remove it
 *   withRetry(fn, {tries, baseMs})         exponential-backoff retry helper
 *   pollHealthAndSurfaceIssues()           checks /api/onboarding/status and
 *                                          shows a banner when ollama is down
 *                                          or the embed model is missing
 *
 * Pulled out of app.js so the recovery UX has one place to grow without
 * bloating the master coordinator.
 */

const BANNER_ID = "recoveryBanner";
const TONES = {
  error: "#7f1d1d",
  warn:  "#78350f",
  info:  "#1e3a8a",
};

const styles = `
#${BANNER_ID} { position: fixed; top: 0; left: 0; right: 0; padding: 10px 16px; display: flex; gap: 12px; align-items: center; z-index: 9997; color: #f9fafb; font-family: -apple-system, BlinkMacSystemFont, "SF Pro", sans-serif; font-size: 13px; box-shadow: 0 2px 12px rgba(0,0,0,.35); }
#${BANNER_ID} .msg { flex: 1; }
#${BANNER_ID} button { border: none; padding: 6px 12px; border-radius: 6px; font-weight: 600; cursor: pointer; background: rgba(255,255,255,.12); color: #f9fafb; }
#${BANNER_ID} button:hover { background: rgba(255,255,255,.22); }
#${BANNER_ID} button.dismiss { background: transparent; opacity: .7; }
#${BANNER_ID} button.dismiss:hover { opacity: 1; background: rgba(255,255,255,.08); }
#${BANNER_ID} code { background: rgba(0,0,0,.35); padding: 1px 5px; border-radius: 3px; font-family: ui-monospace, monospace; }
`;

function ensureStyles() {
  if (document.getElementById(`${BANNER_ID}-css`)) return;
  const el = document.createElement("style");
  el.id = `${BANNER_ID}-css`;
  el.textContent = styles;
  document.head.appendChild(el);
}

/**
 * @param {Object}   o
 * @param {string}   o.message  — HTML string (kept short; caller escapes)
 * @param {"error"|"warn"|"info"} [o.tone]
 * @param {Array<{label: string, onClick: () => void}>} [o.actions]
 * @param {string}   [o.key]    — dedupe key; a banner with the same key
 *                                won't be re-rendered if it's already up
 */
export function showBanner({ message, tone = "warn", actions = [], key = "" }) {
  ensureStyles();
  const existing = document.getElementById(BANNER_ID);
  if (existing && existing.dataset.key === key) return;
  const banner = existing || document.createElement("div");
  banner.id = BANNER_ID;
  banner.dataset.key = key;
  banner.style.background = TONES[tone] || TONES.warn;
  banner.innerHTML = `<div class="msg">${message}</div>`;
  actions.forEach(a => {
    const btn = document.createElement("button");
    btn.textContent = a.label;
    btn.addEventListener("click", () => { try { a.onClick(); } catch {} });
    banner.appendChild(btn);
  });
  const dismiss = document.createElement("button");
  dismiss.className = "dismiss";
  dismiss.setAttribute("aria-label", "Dismiss");
  dismiss.textContent = "×";
  dismiss.addEventListener("click", dismissBanner);
  banner.appendChild(dismiss);
  if (!existing) document.body.appendChild(banner);
}

export function dismissBanner() {
  const b = document.getElementById(BANNER_ID);
  if (b) b.remove();
}

/** Exponential-backoff retry for any async function.
 *  Rethrows the last error after `tries` attempts. */
export async function withRetry(fn, { tries = 3, baseMs = 400 } = {}) {
  let lastErr;
  for (let i = 0; i < tries; i += 1) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (i === tries - 1) break;
      const wait = baseMs * Math.pow(2, i) + Math.random() * baseMs;
      await new Promise(r => setTimeout(r, wait));
    }
  }
  throw lastErr;
}

// ── One-shot ollama pull driver (used from banner "Pull embed" button) ──
async function pullModelBlocking(name) {
  const resp = await fetch("/api/models/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: name }),
    credentials: "include",
  });
  if (!resp.ok || !resp.body) throw new Error(`pull request failed: ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    // Drain complete SSE frames; we don't care about intermediate progress
    // in this path (the banner just spins until we return).
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (frame.includes("event: done")) return;
      if (frame.includes("event: error")) {
        const m = frame.match(/^data:\s*(.*)$/m);
        try { throw new Error(JSON.parse(m[1]).error || "pull error"); }
        catch { throw new Error("pull failed"); }
      }
    }
  }
}

/** Poll /api/onboarding/status once and surface an appropriate recovery
 *  banner if ollama is unreachable or the embedding model is missing.
 *  Call from app.js after DOMContentLoaded. */
export async function pollHealthAndSurfaceIssues() {
  let status;
  try {
    const resp = await fetch("/api/onboarding/status", { credentials: "include" });
    if (!resp.ok) return;
    status = await resp.json();
  } catch { return; }

  if (!status.ollama_up) {
    showBanner({
      key: "ollama-down",
      tone: "error",
      message: `Ollama is not reachable. Start it with <code>ollama serve</code> or <code>brew services start ollama</code>.`,
      actions: [
        {
          label: "Retry",
          onClick: () => { dismissBanner(); pollHealthAndSurfaceIssues(); },
        },
      ],
    });
    return;
  }

  const embedMissing = (status.recommended_missing || []).some(
    m => m.startsWith("nomic-embed") || m === "nomic-embed-text"
  );
  if (embedMissing) {
    let pulling = false;
    showBanner({
      key: "embed-missing",
      tone: "warn",
      message: `RAG is degraded — embed model <code>nomic-embed-text</code> is not installed.`,
      actions: [
        {
          label: "Pull now",
          onClick: async () => {
            if (pulling) return;
            pulling = true;
            showBanner({
              key: "embed-pulling",
              tone: "info",
              message: `Pulling <code>nomic-embed-text</code>… (this can take a minute)`,
              actions: [],
            });
            try {
              await pullModelBlocking("nomic-embed-text");
              showBanner({
                key: "embed-ok",
                tone: "info",
                message: `<code>nomic-embed-text</code> installed. RAG is back.`,
                actions: [{ label: "Reload", onClick: () => location.reload() }],
              });
            } catch (e) {
              showBanner({
                key: "embed-failed",
                tone: "error",
                message: `Pull failed: ${(e && e.message) || "unknown"}. Try <code>ollama pull nomic-embed-text</code> in a terminal.`,
                actions: [{ label: "Retry", onClick: () => pollHealthAndSurfaceIssues() }],
              });
            }
          },
        },
      ],
    });
  }
}
