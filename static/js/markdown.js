/**
 * Markdown renderer for Local LLM Studio.
 * Uses `marked` for CommonMark/GFM parsing, `highlight.js` for syntax highlighting,
 * and `DOMPurify` to sanitize the final HTML — so a model that emits <img onerror=…>
 * or <script> can't run code in the page.
 *
 * All three libs are loaded from esm.sh as ESM (no build step).
 */

import { marked } from "https://esm.sh/marked@14.1.3";
import DOMPurify from "https://esm.sh/dompurify@3.2.7";
import hljs from "https://esm.sh/highlight.js@11.10.0/lib/common";

marked.setOptions({
  gfm: true,
  breaks: true,
  headerIds: false,
  mangle: false,
});

// Wrap code blocks with our copy-button UI + language label + hljs highlighting.
const renderer = new marked.Renderer();
renderer.code = function (code, infoString /*, escaped */) {
  const raw = typeof code === "string" ? code : (code && code.text) || "";
  const langInfo = typeof infoString === "string" ? infoString : (code && code.lang) || "";
  const lang = (langInfo || "").split(/\s+/)[0].toLowerCase() || "";
  let highlighted;
  try {
    highlighted = lang && hljs.getLanguage(lang)
      ? hljs.highlight(raw, { language: lang, ignoreIllegals: true }).value
      : hljs.highlightAuto(raw).value;
  } catch {
    highlighted = escapeHtml(raw);
  }
  const codeId = "code-" + Math.random().toString(36).slice(2, 9);
  const runBtn = (lang === "python" || lang === "py")
    ? `<button class="btn-run-code" data-run-target="${codeId}" title="Run in sandbox">▶ Run</button>`
    : "";
  return `<div class="code-block-wrapper">
    <div class="code-block-header">
      <span class="code-lang-label">${escapeHtml(lang || "code")}</span>
      <span class="code-block-actions">
        ${runBtn}
        <button class="btn-copy-code" data-copy-target="${codeId}">📋 Copy code</button>
      </span>
    </div>
    <pre class="code-content"><code id="${codeId}" class="hljs language-${escapeHtml(lang)}">${highlighted}</code></pre>
    <div class="code-run-output" id="out-${codeId}" hidden></div>
  </div>`;
};
marked.use({ renderer });

const PURIFY_CONFIG = {
  ADD_ATTR: ["target", "rel", "data-copy-target"],
  ADD_TAGS: ["details", "summary", "mark"],
  FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form"],
  FORBID_ATTR: ["onerror", "onload", "onclick", "onmouseover", "onfocus"],
};

// Force target=_blank + rel=noopener on all links after purification.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export function parseMarkdown(md) {
  if (!md) return "";

  // Fold <think>...</think> blocks (DeepSeek R1 / QwQ / Qwen3-thinking) into a
  // collapsible <details>. Drop unclosed think blocks that are still streaming.
  let source = md.replace(/<think>([\s\S]*?)<\/think>/gi, (_, content) => {
    const trimmed = content.trim();
    const wordCount = trimmed ? trimmed.split(/\s+/).length : 0;
    return `<details class="think-block"><summary>🧠 Reasoning (${wordCount} words)</summary>\n\n<div class="think-content">\n\n${trimmed}\n\n</div>\n\n</details>\n\n`;
  });
  source = source.replace(/<think>[\s\S]*$/gi, "");

  const dirty = marked.parse(source);
  return DOMPurify.sanitize(dirty, PURIFY_CONFIG);
}

export function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Delegated copy handler — wired once, works for every code block.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".btn-copy-code");
  if (!btn) return;
  const targetId = btn.getAttribute("data-copy-target");
  const el = targetId ? document.getElementById(targetId) : null;
  if (!el) return;
  navigator.clipboard.writeText(el.innerText);
  const toast = document.createElement("div");
  toast.className = "copy-toast";
  toast.innerText = "Code copied to clipboard!";
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2000);
});

// Delegated Run handler for Python code blocks. Hits /api/sandbox/run and
// renders stdout/stderr inline. On error, shows a "Send error to model" button.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn-run-code");
  if (!btn) return;
  const codeId = btn.getAttribute("data-run-target");
  const codeEl = codeId ? document.getElementById(codeId) : null;
  const outEl = codeId ? document.getElementById(`out-${codeId}`) : null;
  if (!codeEl || !outEl) return;

  const code = codeEl.innerText;
  outEl.hidden = false;
  outEl.innerHTML = `<div class="code-run-status">▶ running in sandbox...</div>`;
  btn.disabled = true;
  try {
    const resp = await fetch("/api/sandbox/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code, timeout: 10 }),
    });
    const data = await resp.json();
    const parts = [];
    parts.push(`<div class="code-run-status ${data.status === "success" ? "ok" : "err"}">${escapeHtml(data.status || "?")}${data.return_code != null ? ` (exit ${data.return_code})` : ""}${data.sandboxed ? " · sandboxed" : ""}</div>`);
    if (data.stdout) parts.push(`<pre class="code-run-stdout">${escapeHtml(data.stdout)}</pre>`);
    if (data.stderr) parts.push(`<pre class="code-run-stderr">${escapeHtml(data.stderr)}</pre>`);
    if (data.error) parts.push(`<div class="code-run-err">${escapeHtml(data.error)}</div>`);
    if ((data.stderr && data.stderr.trim()) || data.return_code !== 0) {
      parts.push(`<button class="btn-run-fix" data-fix-code="${escapeAttr(code)}" data-fix-error="${escapeAttr((data.stderr || data.error || '').slice(0, 2000))}">🔧 Ask model to fix</button>`);
    }
    outEl.innerHTML = parts.join("");
  } catch (err) {
    outEl.innerHTML = `<div class="code-run-err">Run failed: ${escapeHtml(String(err))}</div>`;
  } finally {
    btn.disabled = false;
  }
});

// Delegated "Ask model to fix" — drop the code + error into the composer so
// the user can hit Send with full context.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".btn-run-fix");
  if (!btn) return;
  const code = btn.getAttribute("data-fix-code") || "";
  const err = btn.getAttribute("data-fix-error") || "";
  const composer = document.getElementById("composerTextarea");
  if (!composer) return;
  composer.value = `The following Python fails. Fix it and explain what was wrong.\n\n\`\`\`python\n${code}\n\`\`\`\n\nError:\n\`\`\`\n${err}\n\`\`\``;
  composer.focus();
  composer.dispatchEvent(new Event("input", { bubbles: true }));
});

function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Back-compat shim for any code that still calls window.copyCodeBlock(id).
window.copyCodeBlock = function (codeId) {
  const el = document.getElementById(codeId);
  if (!el) return;
  navigator.clipboard.writeText(el.innerText);
};
