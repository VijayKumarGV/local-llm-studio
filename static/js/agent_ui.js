/**
 * Agent UI Component: Multi-step timelines, tool cards, and citations
 */

import { escapeHtml } from "./markdown.js";

export function createToolCardHtml(toolName, status, result) {
  const icon = toolName === "search_web" ? "🌐" : (toolName === "execute_python_code" ? "🐍" : (toolName === "create_artifact" ? "📦" : "📁"));
  const label = toolName === "search_web" ? "Web Search" : (toolName === "execute_python_code" ? "Python Execution" : (toolName === "create_artifact" ? "Create Artifact" : toolName));
  const resultPreview = typeof result === "object" ? JSON.stringify(result, null, 2) : String(result);
  const isRunning = status === "running";

  return `
    <div class="tool-execution-card">
      <div class="tool-card-header" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <div style="display:flex; align-items:center; gap:8px;">
          <span>${icon}</span>
          <span><strong>${label}</strong></span>
        </div>
        <span class="tool-status-pill ${status}">
          ${isRunning ? '⏳ Running...' : '✓ ' + status}
        </span>
      </div>
      <div class="tool-card-body ${isRunning ? '' : 'hidden'}">${escapeHtml(resultPreview)}</div>
    </div>
  `;
}

export function createCitationCardHtml(citations) {
  if (!citations || citations.length === 0) return "";
  let html = `<div class="citations-container" style="margin-top:10px; border-top:1px solid var(--border-subtle); padding-top:8px;">`;
  html += `<div style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">📚 Sources & Citations</div>`;
  html += `<div style="display:flex; flex-wrap:wrap; gap:8px;">`;

  citations.forEach((c, idx) => {
    html += `
      <a href="${c.url || '#'}" target="_blank" rel="noopener noreferrer" class="citation-pill" title="${escapeHtml(c.snippet || '')}" style="display:inline-flex; align-items:center; gap:4px; font-size:0.75rem; background:rgba(56,189,248,0.1); color:var(--accent-cyan); border:1px solid rgba(56,189,248,0.25); border-radius:6px; padding:2px 8px; text-decoration:none;">
        <span>[${idx + 1}]</span>
        <span style="max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(c.title)}</span>
      </a>
    `;
  });

  html += `</div></div>`;
  return html;
}
