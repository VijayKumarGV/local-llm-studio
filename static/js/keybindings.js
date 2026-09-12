/**
 * Keyboard-shortcut registry + `?` help overlay.
 *
 * The actual handlers stay in app.js (they close over DOM refs + app
 * state). This module owns:
 *   - the single source-of-truth list of shortcuts (so `?` and any
 *     future docs page can render the same thing)
 *   - the `?` overlay renderer
 *   - a small helper to install the overlay's keydown handler
 *
 * Import + call `installShortcutsHelp()` once from app.js after the
 * DOM is ready.
 */

export const SHORTCUTS = [
  { keys: ["⌘K"],       action: "Command palette / search" },
  { keys: ["⌘N"],       action: "New conversation" },
  { keys: ["⌘B"],       action: "Toggle sidebar" },
  { keys: ["⌘⇧M"],      action: "Cycle model" },
  { keys: ["⌘/"],       action: "Focus composer" },
  { keys: ["⌘↵"],       action: "Send message" },
  { keys: ["⌘⇧R"],      action: "Regenerate last response" },
  { keys: ["⌘,"],       action: "Open settings" },
  { keys: ["?"],        action: "Show this help" },
  { keys: ["Esc"],      action: "Close modals / stop stream" },
];

const OVERLAY_ID = "shortcutsOverlay";

const styles = `
#${OVERLAY_ID} { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: none; align-items: center; justify-content: center; z-index: 9998; font-family: -apple-system, BlinkMacSystemFont, "SF Pro", sans-serif; }
#${OVERLAY_ID}.open { display: flex; }
#${OVERLAY_ID} .card { background: #111827; color: #f9fafb; border-radius: 12px; padding: 24px 28px; min-width: 360px; box-shadow: 0 20px 60px rgba(0,0,0,.4); }
#${OVERLAY_ID} h3 { margin: 0 0 14px; font-size: 16px; }
#${OVERLAY_ID} table { border-collapse: collapse; }
#${OVERLAY_ID} td { padding: 6px 12px 6px 0; font-size: 13px; }
#${OVERLAY_ID} kbd { background: #1f2937; padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, monospace; font-size: 12px; color: #a3e635; }
#${OVERLAY_ID} .hint { color: #9ca3af; font-size: 12px; margin-top: 12px; }
`;

function ensureStyles() {
  if (document.getElementById(`${OVERLAY_ID}-css`)) return;
  const el = document.createElement("style");
  el.id = `${OVERLAY_ID}-css`;
  el.textContent = styles;
  document.head.appendChild(el);
}

function ensureOverlay() {
  let overlay = document.getElementById(OVERLAY_ID);
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  const rows = SHORTCUTS.map(s =>
    `<tr><td>${s.keys.map(k => `<kbd>${k}</kbd>`).join(" ")}</td><td>${s.action}</td></tr>`
  ).join("");
  overlay.innerHTML = `
    <div class="card" role="dialog" aria-modal="true" aria-labelledby="shortcutsTitle">
      <h3 id="shortcutsTitle">Keyboard shortcuts</h3>
      <table>${rows}</table>
      <div class="hint">Esc closes this. On non-Mac replace ⌘ with Ctrl.</div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeShortcutsHelp();
  });
  return overlay;
}

export function openShortcutsHelp() {
  ensureStyles();
  ensureOverlay().classList.add("open");
}

export function closeShortcutsHelp() {
  const o = document.getElementById(OVERLAY_ID);
  if (o) o.classList.remove("open");
}

export function isShortcutsHelpOpen() {
  const o = document.getElementById(OVERLAY_ID);
  return !!o && o.classList.contains("open");
}

/** True when the event target is a text input / textarea / editable
 * — we don't want `?` to fire while the user is typing a message. */
export function isTypingContext(target) {
  if (!target) return false;
  const tag = (target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea") return true;
  return !!target.isContentEditable;
}

/**
 * Wire `?` and `Esc` for the overlay. Call once at app startup.
 * Returns the listener so callers can `window.removeEventListener` if
 * they need to (tests, hot-reload).
 */
export function installShortcutsHelp() {
  const listener = (e) => {
    if (e.key === "Escape" && isShortcutsHelpOpen()) {
      e.preventDefault();
      closeShortcutsHelp();
      return;
    }
    if (e.key === "?" && !isTypingContext(e.target) && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      openShortcutsHelp();
    }
  };
  window.addEventListener("keydown", listener);
  return listener;
}
