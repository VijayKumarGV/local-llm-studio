/**
 * Artifacts UI Component: Slide-out drawer, preview, and download
 */

import { escapeHtml } from "./markdown.js";

export function renderArtifactDrawer(artifact, containerEl) {
  if (!containerEl) return;

  containerEl.innerHTML = `
    <div class="artifact-drawer-header">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-size:1.2rem;">📦</span>
        <div>
          <div style="font-weight:700; font-size:0.95rem;">${escapeHtml(artifact.name)}</div>
          <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(artifact.type)} • ${artifact.size_bytes} bytes</div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <button class="btn-icon" onclick="window.downloadArtifact('${artifact.id}')" title="Download File">📥</button>
        <button class="btn-icon" onclick="window.closeArtifactDrawer()" title="Close Drawer">✕</button>
      </div>
    </div>
    <div class="artifact-drawer-body">
      <pre style="background:#0d1117; padding:14px; border-radius:8px; overflow-x:auto; font-family:monospace; font-size:0.85rem; color:#e6edf3;"><code>${escapeHtml(artifact.content)}</code></pre>
    </div>
  `;
}

window.downloadArtifact = function(artifactId) {
  window.open(`/api/artifacts/${artifactId}/download`, '_blank');
};
