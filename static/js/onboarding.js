/**
 * First-run setup wizard.
 *
 * On page load: calls GET /api/onboarding/status. If `needs_setup` is
 * true, shows a modal overlay with 5 steps: welcome → pick models →
 * curate corpus → build workspaces → done. Progress from
 * POST /api/models/pull is streamed as SSE and rendered as per-model
 * progress bars.
 *
 * Everything here is scoped inside `#wizardOverlay` so removing that
 * node in DevTools cleanly disables the wizard for the session.
 */

// No import from api.js — this module talks to /api/onboarding/status and
// /api/models/pull directly (both need cookie-auth fetches, no shared
// state), so an extra layer would just be indirection.

const STORAGE_KEY = "studio.wizard.dismissed";

const styles = `
#wizardOverlay { position: fixed; inset: 0; background: rgba(0,0,0,0.66); display: none; align-items: center; justify-content: center; z-index: 9999; font-family: -apple-system, BlinkMacSystemFont, "SF Pro", sans-serif; }
#wizardOverlay.open { display: flex; }
#wizardCard { width: min(680px, 92vw); max-height: 88vh; overflow-y: auto; background: #111827; color: #f9fafb; border-radius: 14px; box-shadow: 0 20px 60px rgba(0,0,0,.4); padding: 28px 28px 20px; }
#wizardCard h2 { margin: 0 0 4px; font-size: 22px; }
#wizardCard .subtle { color: #9ca3af; font-size: 13px; margin-bottom: 18px; }
#wizardCard .steps { display: flex; gap: 6px; margin-bottom: 20px; }
#wizardCard .step-dot { flex: 1; height: 4px; border-radius: 2px; background: #374151; }
#wizardCard .step-dot.active { background: #38bdf8; }
#wizardCard .step-dot.done { background: #22c55e; }
#wizardCard .model-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid #1f2937; }
#wizardCard .model-row:last-child { border-bottom: none; }
#wizardCard .model-row input[type=checkbox] { width: 18px; height: 18px; }
#wizardCard .model-name { font-weight: 600; }
#wizardCard .model-desc { color: #9ca3af; font-size: 12px; }
#wizardCard .progress-outer { background: #1f2937; border-radius: 6px; height: 8px; overflow: hidden; margin-top: 6px; }
#wizardCard .progress-inner { background: #38bdf8; height: 100%; width: 0; transition: width .2s ease; }
#wizardCard .progress-label { font-size: 11px; color: #9ca3af; margin-top: 3px; }
#wizardCard .actions { display: flex; justify-content: space-between; align-items: center; margin-top: 22px; padding-top: 16px; border-top: 1px solid #1f2937; }
#wizardCard button { border: none; padding: 8px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; }
#wizardCard button.primary { background: #38bdf8; color: #0f172a; }
#wizardCard button.primary:disabled { background: #1f2937; color: #4b5563; cursor: not-allowed; }
#wizardCard button.ghost { background: transparent; color: #9ca3af; }
#wizardCard button.ghost:hover { color: #f9fafb; }
#wizardCard .status-line { color: #a3e635; font-size: 12px; margin-top: 6px; }
#wizardCard .error-line { color: #f87171; font-size: 12px; margin-top: 6px; }
`;

const MODEL_META = {
  "nomic-embed-text":       { size: "0.3 GB", desc: "Embeddings for RAG. Required.", required: true },
  "qwen2.5:32b":            { size: "19 GB",  desc: "General-purpose 32B chat model." },
  "qwen2.5-coder:32b":      { size: "19 GB",  desc: "Coding-tuned 32B; default for Coding Expert." },
  "llama3.2:1b":            { size: "1.3 GB", desc: "Fast triage / routing / HyDE queries." },
};

function ensureStyles() {
  if (document.getElementById("wizardStyles")) return;
  const el = document.createElement("style");
  el.id = "wizardStyles";
  el.textContent = styles;
  document.head.appendChild(el);
}

function ensureOverlay() {
  let overlay = document.getElementById("wizardOverlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "wizardOverlay";
  overlay.innerHTML = `<div id="wizardCard" role="dialog" aria-modal="true" aria-labelledby="wizardTitle"></div>`;
  document.body.appendChild(overlay);
  return overlay;
}

function renderSteps(current, total, doneUpTo) {
  return Array.from({ length: total }, (_, i) => {
    const cls = i < doneUpTo ? "step-dot done" : (i === current ? "step-dot active" : "step-dot");
    return `<div class="${cls}"></div>`;
  }).join("");
}

async function pullModelWithProgress(name, onProgress) {
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
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const evt = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const eventMatch = evt.match(/^event: (\S+)/m);
      const dataMatch = evt.match(/^data: (.*)$/m);
      if (!eventMatch || !dataMatch) continue;
      const kind = eventMatch[1];
      let payload;
      try { payload = JSON.parse(dataMatch[1]); } catch { continue; }
      onProgress(kind, payload);
      if (kind === "done") return payload;
      if (kind === "error") throw new Error(payload.error || "pull error");
    }
  }
  throw new Error("pull stream ended without done");
}

class Wizard {
  constructor(status) {
    this.status = status;
    this.step = 0;                    // 0-based
    this.total = 5;
    this.selected = new Set(status.recommended_missing);
    this.pullStates = {};             // name → { pct, label, done, error }
    this.corpusRunning = false;
    this.workspacesRunning = false;
    ensureStyles();
    this.overlay = ensureOverlay();
    this.card = this.overlay.querySelector("#wizardCard");
    this.overlay.classList.add("open");
    this.render();
  }

  close(dismissed = true) {
    if (dismissed) try { localStorage.setItem(STORAGE_KEY, "1"); } catch {}
    this.overlay.classList.remove("open");
  }

  next() { if (this.step < this.total - 1) { this.step += 1; this.render(); } }
  back() { if (this.step > 0)               { this.step -= 1; this.render(); } }

  render() {
    const dots = renderSteps(this.step, this.total, this.step);
    let body = "";
    switch (this.step) {
      case 0: body = this.renderWelcome(); break;
      case 1: body = this.renderModels(); break;
      case 2: body = this.renderCorpus(); break;
      case 3: body = this.renderWorkspaces(); break;
      case 4: body = this.renderDone(); break;
    }
    this.card.innerHTML = `
      <h2 id="wizardTitle">Local LLM Studio · Setup</h2>
      <div class="subtle">Step ${this.step + 1} of ${this.total}</div>
      <div class="steps">${dots}</div>
      ${body}
      <div class="actions">
        <button class="ghost" data-act="skip">Skip setup</button>
        <div>
          ${this.step > 0 ? `<button class="ghost" data-act="back">Back</button>` : ""}
          <button class="primary" data-act="next" ${this.canAdvance() ? "" : "disabled"}>${this.step === this.total - 1 ? "Done" : "Next"}</button>
        </div>
      </div>
    `;
    this.card.querySelectorAll("[data-act]").forEach(btn => {
      btn.addEventListener("click", () => this.handle(btn.dataset.act));
    });
    if (this.step === 1) this.attachModelHandlers();
    if (this.step === 2) this.attachCorpusHandler();
    if (this.step === 3) this.attachWorkspacesHandler();
  }

  canAdvance() {
    if (this.step === 1) {
      // Every selected model must be either done or absent from the pulling map.
      return Object.values(this.pullStates).every(s => s.done || s.error) || this.selected.size === 0;
    }
    return true;
  }

  handle(action) {
    if (action === "skip")    return this.close(true);
    if (action === "back")    return this.back();
    if (action === "next" && this.step === this.total - 1) return this.close(false);
    if (action === "next")    return this.next();
  }

  renderWelcome() {
    const ollama = this.status.ollama_up ? "✅ reachable" : "❌ not reachable — start it with <code>ollama serve</code>";
    return `
      <p>This wizard installs the recommended models and provisions the two expert workspaces (<b>Security</b> + <b>Coding</b>) so you can start chatting in a few minutes.</p>
      <ul>
        <li>Ollama: ${ollama}</li>
        <li>Models installed: ${this.status.models_installed.length}</li>
        <li>Workspaces: ${this.status.workspaces_created}</li>
        <li>Corpus present: ${this.status.corpus_downloaded ? "yes" : "no"}</li>
      </ul>
    `;
  }

  renderModels() {
    const rows = Object.entries(MODEL_META).map(([name, meta]) => {
      const already = !this.status.recommended_missing.includes(name);
      const state = this.pullStates[name];
      const checked = this.selected.has(name);
      const disabled = already ? "disabled" : "";
      const label = already ? " (installed)" : ` (${meta.size})`;
      let progress = "";
      if (state) {
        const pct = Math.round((state.pct || 0) * 100);
        const label2 = state.error ? `<div class="error-line">${state.error}</div>`
                    : state.done  ? `<div class="status-line">✓ pulled</div>`
                                  : `<div class="progress-label">${state.label || "…"}</div>`;
        progress = `<div class="progress-outer"><div class="progress-inner" style="width:${pct}%"></div></div>${label2}`;
      }
      return `
        <div class="model-row" data-model="${name}">
          <input type="checkbox" ${checked ? "checked" : ""} ${disabled} data-model-check="${name}"/>
          <div style="flex:1">
            <div class="model-name">${name}${label}</div>
            <div class="model-desc">${meta.desc}</div>
            ${progress}
          </div>
        </div>
      `;
    }).join("");
    return `
      <p>Pick which models to download. You can add or remove later from Settings.</p>
      ${rows}
      <button class="primary" data-act="pull" style="margin-top:10px" ${this.pullingAny() ? "disabled" : ""}>
        ${this.pullingAny() ? "Downloading…" : "Download selected"}
      </button>
    `;
  }

  pullingAny() {
    return Object.values(this.pullStates).some(s => !s.done && !s.error);
  }

  attachModelHandlers() {
    this.card.querySelectorAll("[data-model-check]").forEach(cb => {
      cb.addEventListener("change", () => {
        const name = cb.dataset.modelCheck;
        if (cb.checked) this.selected.add(name); else this.selected.delete(name);
      });
    });
    const pullBtn = this.card.querySelector("[data-act='pull']");
    if (pullBtn) pullBtn.addEventListener("click", () => this.beginPulls());
  }

  async beginPulls() {
    const targets = [...this.selected].filter(n => this.status.recommended_missing.includes(n));
    for (const name of targets) {
      this.pullStates[name] = { pct: 0, label: "starting", done: false };
    }
    this.render();
    await Promise.all(targets.map(name => this.pullOne(name)));
    this.render();
  }

  async pullOne(name) {
    try {
      await pullModelWithProgress(name, (kind, payload) => {
        const st = this.pullStates[name];
        if (!st) return;
        if (kind === "progress") {
          if (payload.total && payload.completed != null) {
            st.pct = payload.completed / payload.total;
            const mb = (payload.completed / 1024 / 1024).toFixed(0);
            const tot = (payload.total / 1024 / 1024).toFixed(0);
            st.label = `${payload.status || "downloading"}: ${mb} / ${tot} MB`;
          } else if (payload.status) {
            st.label = payload.status;
          }
        } else if (kind === "done") {
          st.done = true; st.pct = 1; st.label = "done";
        }
        this.render();
      });
    } catch (e) {
      this.pullStates[name].error = String(e.message || e);
      this.render();
    }
  }

  renderCorpus() {
    if (this.status.corpus_downloaded) {
      return `<p>Corpus is already downloaded (<code>corpus/</code> is non-empty). You can rebuild any time via <code>make first-run</code>.</p>`;
    }
    return `
      <p>Download the curated reference corpus for the two experts (OWASP + MITRE for Security, Rust/Python/Go/TS docs for Coding).</p>
      <p class="subtle">This shells out to <code>scripts/curate_corpus.py</code> inside the studio container. First run takes a few minutes; re-runs are near-instant.</p>
      <div class="status-line" id="corpusStatus" style="display:none"></div>
      <div class="error-line" id="corpusError" style="display:none"></div>
      <button class="primary" data-act="run-corpus" ${this.corpusRunning ? "disabled" : ""}>
        ${this.corpusRunning ? "Curating…" : "Download corpus"}
      </button>
    `;
  }

  attachCorpusHandler() {
    const btn = this.card.querySelector("[data-act='run-corpus']");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      this.corpusRunning = true;
      this.render();
      try {
        // The playbook says a dedicated endpoint would spawn the script;
        // until that lands, surface the CLI command so the operator can
        // run it in a terminal without leaving the wizard.
        const msg = "Run this in a terminal:\n\n  make first-run\n\nOr, inside the container:\n\n  python scripts/curate_corpus.py";
        alert(msg);
      } finally {
        this.corpusRunning = false;
        this.render();
      }
    });
  }

  renderWorkspaces() {
    if (this.status.workspaces_created > 0) {
      return `<p>You already have ${this.status.workspaces_created} workspace(s). Skip ahead unless you want to reprovision.</p>`;
    }
    return `
      <p>Provision the two expert workspaces: <b>Security Expert</b> and <b>Coding Expert</b>. Each gets a system prompt, default model, and ingested corpus.</p>
      <p class="subtle">Same story as the corpus — this runs <code>scripts/build_expert_workspaces.py</code>.</p>
      <button class="primary" data-act="run-workspaces" ${this.workspacesRunning ? "disabled" : ""}>
        ${this.workspacesRunning ? "Building…" : "Build workspaces"}
      </button>
    `;
  }

  attachWorkspacesHandler() {
    const btn = this.card.querySelector("[data-act='run-workspaces']");
    if (!btn) return;
    btn.addEventListener("click", () => {
      alert("Run:\n\n  make first-run\n\nor:\n\n  python scripts/build_expert_workspaces.py");
    });
  }

  renderDone() {
    return `
      <p>You're set. Some things worth knowing:</p>
      <ul>
        <li><b>⌘K</b> opens the command palette; <b>?</b> shows all shortcuts.</li>
        <li>Attach files by dragging them into the composer.</li>
        <li>Each response gets 👍 / 👎 buttons — feedback tunes RAG weights over time.</li>
        <li>Metrics dashboards: <code>make obs-up</code> → http://localhost:3000</li>
      </ul>
    `;
  }
}

/** Public entry point. Fetches status; opens the wizard iff needed. */
export async function maybeShowWizard({ force = false } = {}) {
  try {
    if (!force && localStorage.getItem(STORAGE_KEY)) return;
    const resp = await fetch("/api/onboarding/status", { credentials: "include" });
    if (!resp.ok) return;
    const status = await resp.json();
    if (!force && !status.needs_setup) return;
    new Wizard(status);
  } catch (e) {
    console.warn("[wizard] status fetch failed", e);
  }
}
