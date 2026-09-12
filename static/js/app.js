/**
 * Master Application Coordinator for Local LLM Studio
 * Imports modular services and coordinates UI state, streaming, projects, and events.
 */

import { state, on, emit } from "./state.js";
import { api } from "./api.js";
import { parseMarkdown, escapeHtml } from "./markdown.js";
import { createToolCardHtml, createCitationCardHtml } from "./agent_ui.js";
import { renderArtifactDrawer } from "./artifacts_ui.js";
import { maybeShowWizard } from "./onboarding.js";
import { installShortcutsHelp } from "./keybindings.js";
import { pollHealthAndSurfaceIssues, withRetry, showBanner } from "./recovery.js";
import { installVoiceFeatures } from "./voice.js";

// DOM Elements
const DOM = {
  sidebar: document.getElementById("sidebar"),
  btnToggleSidebar: document.getElementById("btnToggleSidebar"),
  btnNewChat: document.getElementById("btnNewChat"),
  searchTrigger: document.getElementById("searchTrigger"),
  pinnedList: document.getElementById("pinnedList"),
  projectsList: document.getElementById("projectsList"),
  recentList: document.getElementById("recentList"),
  archivedToggle: document.getElementById("archivedToggle"),
  archivedCount: document.getElementById("archivedCount"),
  archivedArrow: document.getElementById("archivedArrow"),
  archivedList: document.getElementById("archivedList"),
  messagesViewport: document.getElementById("messagesViewport"),
  chatTitle: document.getElementById("chatTitle"),
  projectTag: document.getElementById("projectTag"),
  modelSelector: document.getElementById("modelSelector"),
  composerTextarea: document.getElementById("composerTextarea"),
  attachmentStrip: document.getElementById("attachmentStrip"),
  btnAttachFile: document.getElementById("btnAttachFile"),
  fileInput: document.getElementById("fileInput"),
  projectFileInput: document.getElementById("projectFileInput"),
  btnToggleWebSearch: document.getElementById("btnToggleWebSearch"),
  btnToggleThinkDeeply: document.getElementById("btnToggleThinkDeeply"),
  btnPromptTemplates: document.getElementById("btnPromptTemplates"),
  btnToggleCodeExec: document.getElementById("btnToggleCodeExec"),
  btnSendMessage: document.getElementById("btnSendMessage"),
  btnStopStream: document.getElementById("btnStopStream"),
  dragOverlay: document.getElementById("dragOverlay"),
  contextMenu: document.getElementById("contextMenu"),
  artifactDrawer: document.getElementById("artifactDrawer"),
  // Modals
  searchModal: document.getElementById("searchModal"),
  searchModalInput: document.getElementById("searchModalInput"),
  searchResultsList: document.getElementById("searchResultsList"),
  settingsModal: document.getElementById("settingsModal"),
  projectModal: document.getElementById("projectModal"),
  projectModalTitle: document.getElementById("projectModalTitle"),
  editingProjectId: document.getElementById("editingProjectId"),
  projectNameInput: document.getElementById("projectNameInput"),
  projectDescInput: document.getElementById("projectDescInput"),
  projectInstructionsInput: document.getElementById("projectInstructionsInput"),
  btnSaveProject: document.getElementById("btnSaveProject"),
  moveProjectModal: document.getElementById("moveProjectModal"),
  moveTargetConvId: document.getElementById("moveTargetConvId"),
  moveProjectSelect: document.getElementById("moveProjectSelect"),
  btnConfirmMoveProject: document.getElementById("btnConfirmMoveProject"),
  activeGpuModel: document.getElementById("activeGpuModel")
};

let showArchived = false;

// ==========================================
// INITIALIZATION
// ==========================================

document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await loadInitialData();

  if (state.conversations.length > 0) {
    const firstActive = state.conversations.find(c => c.archived === 0) || state.conversations[0];
    selectConversation(firstActive.id);
  } else {
    createNewConversation();
  }

  // Non-blocking: pops the setup wizard iff /api/onboarding/status reports
  // needs_setup and the user hasn't previously dismissed it.
  maybeShowWizard();
  // Also non-blocking: surface a recovery banner if ollama is unreachable
  // or the embed model is missing.
  pollHealthAndSurfaceIssues();
  // Attach the mic + 🔊 buttons iff whisper/piper are installed.
  installVoiceFeatures();
});

async function loadInitialData() {
  const [settingsRes, modelsRes, projectsRes, convsRes] = await Promise.all([
    api.getSettings(),
    api.getModels(),
    api.getProjects(),
    api.getConversations(null, true)
  ]);

  if (settingsRes.status === "success") state.settings = settingsRes.settings;
  if (modelsRes.status === "success") {
    state.models = modelsRes.models;
    populateModelSelector();
  }
  if (projectsRes.status === "success") {
    state.projects = projectsRes.projects;
    renderProjects();
  }
  if (convsRes.status === "success") {
    state.conversations = convsRes.conversations;
    renderConversations();
  }
}

function populateModelSelector() {
  const preferred = state.settings.default_model || "";
  DOM.modelSelector.innerHTML = "";

  // Ordering hints: prefer larger/smarter models first
  const ORDER_HINTS = ["70b", "32b", "27b", "24b", "14b", "13b", "8b", "7b", "3b"];
  const sorted = [...state.models].sort((a, b) => {
    const ai = ORDER_HINTS.findIndex(h => a.name.includes(h));
    const bi = ORDER_HINTS.findIndex(h => b.name.includes(h));
    if (ai === -1 && bi === -1) return 0;
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  sorted.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m.name;
    const caps = m.capabilities || {};
    const tags = [];
    if (caps.vision) tags.push("👁");
    if (caps.thinking) tags.push("🧠");
    if (caps.tools) tags.push("🔧");
    if (caps.coding === "elite") tags.push("💻");
    const ctxK = caps.context_window ? Math.round(caps.context_window / 1024) + "K" : "";
    const tagStr = tags.length ? " " + tags.join("") : "";
    const ctxStr = ctxK ? ` · ${ctxK}` : "";
    opt.innerText = `${m.name}${tagStr}${ctxStr}`;
    opt.title = caps.description || m.name;
    if (preferred && m.name === preferred) opt.selected = true;
    DOM.modelSelector.appendChild(opt);
  });

  // Also populate settings modal default model selector
  const settingsSel = document.getElementById("settingDefaultModel");
  if (settingsSel) {
    settingsSel.innerHTML = DOM.modelSelector.innerHTML;
    if (preferred) settingsSel.value = preferred;
  }

  if (DOM.activeGpuModel) {
    DOM.activeGpuModel.innerText = DOM.modelSelector.value || "M4 Pro (37GB unified)";
  }
}


// ==========================================
// EVENT LISTENERS & SHORTCUTS
// ==========================================

function setupEventListeners() {
  DOM.btnToggleSidebar?.addEventListener("click", () => toggleSidebar());
  DOM.btnNewChat?.addEventListener("click", () => createNewConversation(state.activeProjectFilter));

  // Delegated data-action handlers (replaces inline onclick= in index.html)
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    switch (action) {
      case "new-project": window.openNewProjectModal?.(); break;
      case "open-settings": window.openSettingsModal?.(); break;
      case "toggle-sidebar": toggleSidebar(); break;
      case "export-conversation":
        if (state.currentConversationId) window.exportConv?.(state.currentConversationId);
        break;
      case "close-modals": window.closeAllModals?.(); break;
      case "export-workspace": window.exportWorkspaceBackup?.(); break;
      case "import-workspace": window.importWorkspaceBackup?.(); break;
      case "save-settings": window.saveSettingsFromModal?.(); break;
    }
  });

  // ⚖️ Compare delegated handler
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-compare-msg]");
    if (!btn) return;
    const mid = btn.getAttribute("data-compare-msg");
    // Find the user prompt this assistant message was responding to
    const conv = state.currentConversation;
    if (!conv || !conv.messages) return showToast("No conversation loaded");
    const idx = conv.messages.findIndex(m => m.id === mid);
    if (idx <= 0) return showToast("No prior user message to compare");
    let userMsg = null;
    for (let i = idx - 1; i >= 0; i--) {
      if (conv.messages[i].role === "user") { userMsg = conv.messages[i]; break; }
    }
    if (!userMsg) return showToast("No user prompt found");
    const currentModel = DOM.modelSelector?.value || "qwen2.5:32b";
    openCompareModal(userMsg.content, currentModel);
  });

  // Promote title="..." → data-tooltip on every existing + future button.
  // We do this once at init AND on every DOM mutation of the messages viewport.
  installTooltips(document.body);
  const mo = new MutationObserver(muts => {
    for (const m of muts) {
      m.addedNodes.forEach(n => {
        if (n.nodeType === 1) installTooltips(n);
      });
    }
  });
  mo.observe(document.body, { childList: true, subtree: true });

  // Message overflow (⋯ More) delegated handler
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-overflow-trigger]");
    if (trigger) {
      const menu = trigger.nextElementSibling;
      const wasOpen = menu?.classList.contains("open");
      // Close any other open menus
      document.querySelectorAll(".msg-overflow-menu.open").forEach(m => m.classList.remove("open"));
      if (!wasOpen && menu) menu.classList.add("open");
      e.stopPropagation();
      return;
    }
    // Click outside any open menu closes it
    if (!e.target.closest(".msg-overflow-menu")) {
      document.querySelectorAll(".msg-overflow-menu.open").forEach(m => m.classList.remove("open"));
    }
  });

  // 👍 / 👎 delegated handler
  document.addEventListener("click", async (e) => {
    const up = e.target.closest("[data-thumb-up]");
    const dn = e.target.closest("[data-thumb-down]");
    const btn = up || dn;
    if (!btn) return;
    const mid = up ? up.getAttribute("data-thumb-up") : dn.getAttribute("data-thumb-down");
    const rating = up ? 1 : -1;
    // Toggle: if this thumb is already active, unrate
    const wasActive = btn.classList.contains("active");
    const finalRating = wasActive ? 0 : rating;
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message_id: mid, rating: finalRating }),
      });
      // Toggle visual state — clear both, set the clicked one if active
      const row = document.querySelector(`.message-row[data-id="${mid}"]`);
      if (row) {
        row.querySelectorAll(".btn-thumb").forEach(b => b.classList.remove("active"));
        if (finalRating !== 0) btn.classList.add("active");
      }
      showToast?.(finalRating === 0 ? "Rating cleared" : (finalRating > 0 ? "Thanks! 👍" : "Feedback saved"));
    } catch (err) {
      console.error("feedback failed", err);
    }
  });

  // Composer auto-resize & Draft Autosave
  DOM.composerTextarea?.addEventListener("input", () => {
    autoResizeComposer();
    saveDraft();
  });

  DOM.composerTextarea?.addEventListener("keydown", (e) => {
    // ⌘↵ / Ctrl↵ always sends, regardless of the enter_to_send setting.
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendMessage();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      if (state.settings.enter_to_send !== "false") {
        e.preventDefault();
        sendMessage();
      }
    }
  });

  DOM.btnSendMessage?.addEventListener("click", sendMessage);
  DOM.btnStopStream?.addEventListener("click", stopGeneration);

  // Tool Toggles
  DOM.btnToggleWebSearch?.addEventListener("click", () => {
    state.tools.webSearch = !state.tools.webSearch;
    DOM.btnToggleWebSearch.classList.toggle("active", state.tools.webSearch);
  });

  DOM.btnToggleCodeExec?.addEventListener("click", () => {
    state.tools.codeExecution = !state.tools.codeExecution;
    DOM.btnToggleCodeExec.classList.toggle("active", state.tools.codeExecution);
  });

  DOM.btnToggleThinkDeeply?.addEventListener("click", () => {
    state.tools.thinkDeeply = !state.tools.thinkDeeply;
    DOM.btnToggleThinkDeeply.classList.toggle("active", state.tools.thinkDeeply);
  });

  DOM.btnPromptTemplates?.addEventListener("click", openPromptTemplates);

  // Attachments
  DOM.btnAttachFile?.addEventListener("click", () => DOM.fileInput.click());
  DOM.fileInput?.addEventListener("change", handleFileInputChange);

  // Project File Input
  DOM.projectFileInput?.addEventListener("change", handleProjectFileInputChange);

  // Drag & Drop
  window.addEventListener("dragenter", (e) => {
    e.preventDefault();
    DOM.dragOverlay?.classList.add("active");
  });
  DOM.dragOverlay?.addEventListener("dragleave", (e) => {
    e.preventDefault();
    DOM.dragOverlay?.classList.remove("active");
  });
  DOM.dragOverlay?.addEventListener("dragover", (e) => e.preventDefault());
  DOM.dragOverlay?.addEventListener("drop", handleFileDrop);

  // Clipboard Paste (Images / Files)
  window.addEventListener("paste", handleClipboardPaste);

  // Global Search Trigger
  DOM.searchTrigger?.addEventListener("click", openSearchModal);
  DOM.searchModalInput?.addEventListener("input", debounce(handleGlobalSearch, 200));

  // Project Save Button
  DOM.btnSaveProject?.addEventListener("click", handleSaveProject);

  // Move Project Confirm Button
  DOM.btnConfirmMoveProject?.addEventListener("click", handleConfirmMoveProject);

  // Archived Accordion Toggle
  DOM.archivedToggle?.addEventListener("click", () => {
    showArchived = !showArchived;
    if (DOM.archivedList) DOM.archivedList.style.display = showArchived ? "block" : "none";
    if (DOM.archivedArrow) DOM.archivedArrow.innerText = showArchived ? "▼" : "▶";
  });

  // Global Shortcuts
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearchModal();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
      e.preventDefault();
      toggleSidebar();
    }
    if ((e.ctrlKey || e.metaKey || e.altKey) && e.key.toLowerCase() === "n") {
      e.preventDefault();
      createNewConversation(state.activeProjectFilter);
    }
    if ((e.ctrlKey || e.metaKey) && e.key === ",") {
      e.preventDefault();
      openSettingsModal();
    }
    // ⌘/ — focus composer
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      DOM.composerTextarea?.focus();
    }
    // ⌘⇧R — regenerate last assistant message
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "r") {
      e.preventDefault();
      const btn = document.querySelector("[data-action='regenerate']");
      if (btn) btn.click();
    }
    // ⌘⇧M — cycle model selector
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "m") {
      e.preventDefault();
      const sel = DOM.modelSelector;
      if (sel && sel.options.length > 0) {
        sel.selectedIndex = (sel.selectedIndex + 1) % sel.options.length;
        sel.dispatchEvent(new Event("change"));
      }
    }
    if (e.key === "Escape") {
      closeAllModals();
      hideContextMenu();
      window.closeArtifactDrawer();
      if (state.isStreaming) stopGeneration();
    }
  });
  // ⌘↵ in the composer sends the message; already wired inside the
  // textarea keydown handler above (checks metaKey/ctrlKey + Enter).
  // `?` overlay:
  installShortcutsHelp();

  window.addEventListener("click", () => hideContextMenu());
}


// ==========================================
// DRAFTS & RECOVERY
// ==========================================

function saveDraft() {
  if (!state.currentConversationId) return;
  const text = DOM.composerTextarea.value;
  localStorage.setItem(`draft_${state.currentConversationId}`, text);
}

function restoreDraft(convId) {
  const saved = localStorage.getItem(`draft_${convId}`);
  DOM.composerTextarea.value = saved || "";
  autoResizeComposer();
}

function clearDraft(convId) {
  localStorage.removeItem(`draft_${convId}`);
}


// ==========================================
// SIDEBAR & NAVIGATION
// ==========================================

function renderProjects() {
  DOM.projectsList.innerHTML = "";

  const allLi = document.createElement("li");
  allLi.className = `nav-item ${state.activeProjectFilter === null ? 'active' : ''}`;
  allLi.innerHTML = `<span class="nav-item-title">🌐 All Workspaces</span>`;
  allLi.onclick = () => {
    state.activeProjectFilter = null;
    refreshConversations();
    renderProjects();
  };
  DOM.projectsList.appendChild(allLi);

  state.projects.forEach(p => {
    const li = document.createElement("li");
    li.className = `nav-item ${state.activeProjectFilter === p.id ? 'active' : ''}`;
    li.innerHTML = `
      <span class="nav-item-title">${p.icon || '📁'} ${escapeHtml(p.name)}</span>
      <span class="item-badge">${p.conversation_count || 0}</span>
      <button class="item-menu-btn" title="Project Actions">•••</button>
    `;
    li.onclick = (e) => {
      if (e.target.classList.contains("item-menu-btn")) return;
      state.activeProjectFilter = p.id;
      refreshConversations();
      renderProjects();
    };
    const menuBtn = li.querySelector(".item-menu-btn");
    menuBtn.onclick = (e) => {
      e.stopPropagation();
      showProjectContextMenu(e, p);
    };
    DOM.projectsList.appendChild(li);
  });

  // Empty state — only "All Workspaces" is present.
  if (state.projects.length === 0) {
    const li = document.createElement("li");
    li.className = "nav-item empty-cta";
    li.style.cssText = "color: var(--text-muted); cursor: pointer; font-size: 0.85rem;";
    li.innerHTML = `<span class="nav-item-title">＋ Create your first workspace…</span>`;
    li.onclick = () => document.getElementById("btnNewProject")?.click();
    DOM.projectsList.appendChild(li);
  }
}

function renderConversations() {
  DOM.pinnedList.innerHTML = "";
  DOM.recentList.innerHTML = "";
  if (DOM.archivedList) DOM.archivedList.innerHTML = "";

  const active = state.conversations.filter(c => (c.archived === 0 || !c.archived));
  const archived = state.conversations.filter(c => c.archived === 1);

  const pinned = active.filter(c => c.pinned === 1);
  const recent = active.filter(c => c.pinned === 0);

  if (pinned.length === 0) {
    DOM.pinnedList.innerHTML = `<li style="font-size:0.75rem; color:var(--text-muted); padding:4px 8px;">No pinned chats</li>`;
  } else {
    pinned.forEach(c => DOM.pinnedList.appendChild(createConversationItem(c)));
  }

  if (recent.length === 0) {
    DOM.recentList.innerHTML = `<li style="font-size:0.75rem; color:var(--text-muted); padding:4px 8px;">No recent chats</li>`;
  } else {
    recent.forEach(c => DOM.recentList.appendChild(createConversationItem(c)));
  }

  // Update Archived Count & List
  if (DOM.archivedCount) DOM.archivedCount.innerText = archived.length;
  if (DOM.archivedList) {
    if (archived.length === 0) {
      DOM.archivedList.innerHTML = `<li style="font-size:0.75rem; color:var(--text-muted); padding:4px 8px;">No archived chats</li>`;
    } else {
      archived.forEach(c => DOM.archivedList.appendChild(createConversationItem(c, true)));
    }
  }
}

function createConversationItem(conv, isArchived = false) {
  const li = document.createElement("li");
  li.className = `nav-item ${state.currentConversationId === conv.id ? 'active' : ''}`;
  li.innerHTML = `
    <span class="nav-item-title" title="${escapeHtml(conv.title)}">${isArchived ? '📦 ' : ''}${escapeHtml(conv.title)}</span>
    <button class="item-menu-btn" title="Options">•••</button>
  `;
  li.onclick = (e) => {
    if (e.target.classList.contains("item-menu-btn")) return;
    selectConversation(conv.id);
  };
  const menuBtn = li.querySelector(".item-menu-btn");
  menuBtn.onclick = (e) => {
    e.stopPropagation();
    showConversationContextMenu(e, conv);
  };
  return li;
}

async function refreshConversations() {
  const res = await api.getConversations(state.activeProjectFilter, true);
  if (res.status === "success") {
    state.conversations = res.conversations;
    renderConversations();
  }
}

async function refreshProjects() {
  const res = await api.getProjects();
  if (res.status === "success") {
    state.projects = res.projects;
    renderProjects();
  }
}


// ==========================================
// CONVERSATION SELECTION & RENDERING
// ==========================================

async function selectConversation(convId) {
  state.currentConversationId = convId;
  renderConversations();
  restoreDraft(convId);

  const res = await api.getConversation(convId);
  if (res.status === "success") {
    state.currentConversation = res.conversation;
    DOM.chatTitle.innerText = res.conversation.title;

    if (res.conversation.project_id) {
      const p = state.projects.find(x => x.id === res.conversation.project_id);
      DOM.projectTag.style.display = "flex";
      DOM.projectTag.innerText = p ? `${p.icon || '📁'} ${p.name}` : "Project";
    } else {
      DOM.projectTag.style.display = "none";
    }

    if (res.conversation.model) {
      // Only set model if it's actually in the dropdown (installed)
      const opts = Array.from(DOM.modelSelector.options).map(o => o.value);
      if (opts.includes(res.conversation.model)) {
        DOM.modelSelector.value = res.conversation.model;
      } else if (opts.length > 0) {
        DOM.modelSelector.value = opts[0]; // fall back to first installed model
      }
      if (DOM.activeGpuModel) DOM.activeGpuModel.innerText = DOM.modelSelector.value || "no model";
    }

    await renderMessages(res.conversation.messages || []);
    checkAndDisplayArtifacts(convId);
  }
}

async function createNewConversation(projectId = null) {
  const defaultModel = state.settings.default_model || DOM.modelSelector.value || "qwen2.5:32b";
  const res = await api.createConversation({
    title: "New Conversation",
    project_id: projectId,
    model: defaultModel,
    temperature: parseFloat(state.settings.default_temperature || "0.7")
  });
  if (res.status === "success") {
    await refreshConversations();
    selectConversation(res.conversation.id);
    DOM.composerTextarea.focus();
  }
}

async function checkAndDisplayArtifacts(convId) {
  const res = await api.getArtifacts(convId);
  if (res.status === "success" && res.artifacts.length > 0) {
    state.activeArtifacts = res.artifacts;
  }
}


// ==========================================
// CHAT MESSAGES & PROJECT HUB
// ==========================================

async function renderMessages(messages) {
  DOM.messagesViewport.innerHTML = "";

  // If inside an active project, render the Project Hub header
  if (state.activeProjectFilter) {
    const hub = await createProjectHubElement(state.activeProjectFilter);
    if (hub) DOM.messagesViewport.appendChild(hub);
  }

  if (messages.length === 0) {
    renderEmptyState();
    return;
  }
  messages.forEach(msg => {
    DOM.messagesViewport.appendChild(createMessageRow(msg));
  });
  scrollToBottom();
}

async function createProjectHubElement(projectId) {
  const p = state.projects.find(x => x.id === projectId);
  if (!p) return null;

  let files = [];
  try {
    const filesRes = await api.getProjectFiles(projectId);
    if (filesRes.status === "success") files = filesRes.files;
  } catch (err) {
    console.error("Failed to load project files", err);
  }

  const hub = document.createElement("div");
  hub.className = "project-hub";

  let filesHtml = "";
  if (files.length === 0) {
    filesHtml = `<span style="font-size:0.8rem; color:var(--text-muted);">No files attached to this workspace yet.</span>`;
  } else {
    files.forEach(f => {
      filesHtml += `
        <div class="project-file-item">
          <span>📄</span>
          <a href="/api/files/${f.id}" target="_blank" download="${escapeHtml(f.filename)}">${escapeHtml(f.filename)}</a>
          <button class="btn-del-file" onclick="window.deleteProjectFile('${f.id}')" title="Delete file">✕</button>
        </div>
      `;
    });
  }

  hub.innerHTML = `
    <div class="project-hub-header">
      <div>
        <div class="project-hub-title">${p.icon || '📁'} ${escapeHtml(p.name)}</div>
        <div class="project-hub-desc">${escapeHtml(p.description || 'Dedicated workspace')}</div>
      </div>
      <div style="display:flex; gap:8px;">
        <button class="tool-toggle-btn" onclick="window.editProj('${p.id}')">✏️ Edit Workspace</button>
        <button class="tool-toggle-btn" onclick="document.getElementById('projectFileInput').click()">＋ Upload File</button>
      </div>
    </div>
    ${p.system_instructions ? `
      <div class="project-hub-instructions">
        <strong>📋 Workspace Instructions:</strong>
        <div>${escapeHtml(p.system_instructions)}</div>
      </div>
    ` : ''}
    <details class="project-files-section">
      <summary class="project-files-header">
        <span class="project-files-caret">▶</span>
        <span>Workspace Attached Files (${files.length})</span>
      </summary>
      <div class="project-files-grid">${filesHtml}</div>
    </details>
  `;

  return hub;
}

function renderEmptyState() {
  const model = DOM.modelSelector.value || "local model";
  const div = document.createElement("div");
  div.className = "empty-state";
  div.style.cssText = "margin: auto; max-width: 640px; text-align: center; display: flex; flex-direction: column; gap: 16px;";
  div.innerHTML = `
    <div style="font-size: 2.4rem;">⚡</div>
    <h2 style="font-size: 1.5rem; color: var(--accent-cyan);">What would you like to build or explore?</h2>
    <p style="color: var(--text-secondary); font-size: 0.9rem; line-height: 1.6;">
      Powered privately by <strong>Apple M4 Pro · 37 GB unified memory</strong> · No cloud, no censorship, no subscriptions.
      <br>Currently loaded: <code style="color:var(--accent-cyan);">${escapeHtml(model)}</code>
    </p>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; text-align: left;">
      <div class="search-result-item" onclick="window.quickPrompt('Search the web for the latest open-source LLM releases and benchmarks.')">
        <span class="result-title">🌐 Live Web Search</span>
        <span class="result-snippet">Fetch real-time facts and citations</span>
      </div>
      <div class="search-result-item" onclick="window.quickPrompt('Write a complete Python web scraper and save it as a code artifact.')">
        <span class="result-title">📦 Artifact Generation</span>
        <span class="result-snippet">Generate downloadable code files</span>
      </div>
      <div class="search-result-item" onclick="window.quickPrompt('Reason through this step by step: what is 17 multiplied by 293, and explain each step.')">
        <span class="result-title">🧠 Chain-of-Thought</span>
        <span class="result-snippet">Multi-step reasoning problems</span>
      </div>
      <div class="search-result-item" onclick="window.quickPrompt('Explain in depth how transformer attention mechanisms work, with diagrams in ASCII.')">
        <span class="result-title">📖 Deep Explanations</span>
        <span class="result-snippet">No topic is off-limits or filtered</span>
      </div>
    </div>
    <div style="font-size:0.78rem; color:var(--text-muted); margin-top:4px;">
      Tip: Press <code>?</code> for shortcuts · <code>⌘K</code> to search · <a href="#" id="relaunchWizard" style="color:var(--accent-cyan)">Run setup wizard again</a>
    </div>
  `;
  DOM.messagesViewport.appendChild(div);
  const relaunch = div.querySelector("#relaunchWizard");
  if (relaunch) {
    relaunch.addEventListener("click", (e) => {
      e.preventDefault();
      maybeShowWizard({ force: true });
    });
  }
}

window.quickPrompt = function(text) {
  DOM.composerTextarea.value = text;
  autoResizeComposer();
  sendMessage();
};

function getModelAvatarLabel(modelName) {
  if (!modelName) return "AI";
  const name = modelName.toLowerCase();
  if (name.includes("qwen")) return "QW";
  if (name.includes("deepseek")) return "DS";
  if (name.includes("dolphin")) return "🐬";
  if (name.includes("hermes")) return "H3";
  if (name.includes("llama")) return "🦙";
  if (name.includes("mistral")) return "MS";
  if (name.includes("gemma")) return "GM";
  if (name.includes("phi")) return "Φ";
  if (name.includes("codellama")) return "CL";
  if (name.includes("llava")) return "👁";
  return modelName.substring(0, 2).toUpperCase();
}

function getModelDisplayName(modelName) {
  if (!modelName) return "Assistant";
  return modelName.split(":")[0];
}

function createMessageRow(msg) {
  const row = document.createElement("div");
  row.className = `message-row ${msg.role}`;
  row.dataset.id = msg.id;

  const isUser = msg.role === "user";
  const currentModel = DOM.modelSelector?.value || "assistant";
  const avatarText = isUser ? "You" : getModelAvatarLabel(currentModel);
  const displayName = isUser ? "You" : getModelDisplayName(currentModel);

  let attachmentsHtml = "";
  if (msg.attachments && msg.attachments.length > 0) {
    attachmentsHtml = `<div class="attachment-strip" style="padding: 0 0 8px 0;">`;
    msg.attachments.forEach(att => {
      const isImg = (att.mime_type && att.mime_type.startsWith("image/")) || /\.(png|jpe?g|webp|gif)$/i.test(att.filename || "");
      const thumb = isImg && att.id ? `<img src="/api/files/${att.id}" class="attachment-thumb" />` : `<span>📄</span>`;
      attachmentsHtml += `<div class="attachment-chip">${thumb}<span>${escapeHtml(att.filename)}</span></div>`;
    });
    attachmentsHtml += `</div>`;
  }

  let toolsHtml = "";
  if (msg.tool_calls && msg.tool_calls.length > 0) {
    msg.tool_calls.forEach(tc => {
      toolsHtml += createToolCardHtml(tc.tool, "success", tc.result);
    });
  }

  const renderedContent = isUser ? escapeHtml(msg.content) : parseMarkdown(msg.content);

  row.innerHTML = `
    <div class="message-avatar ${isUser ? 'user' : 'ai'}">${avatarText}</div>
    <div class="message-body">
      <div class="message-header-info">
        <span>${escapeHtml(displayName)}</span>
        ${msg.eval_tps ? `<span class="token-speed-tag">⚡ ${msg.token_count || 0} tokens · ${msg.eval_tps} tok/s</span>` : ''}
      </div>
      ${attachmentsHtml}
      ${toolsHtml}
      <div class="message-content">${renderedContent}</div>
      <div class="message-toolbar">
        <button class="btn-msg-action" onclick="window.copyMessage('${msg.id}')" title="Copy message text">📋 Copy</button>
        ${!isUser ? `
          <button class="btn-msg-action btn-thumb" data-thumb-up="${msg.id}" title="Rate this response 👍">👍</button>
          <button class="btn-msg-action btn-thumb" data-thumb-down="${msg.id}" title="Rate this response 👎">👎</button>
        ` : ''}
        ${isUser ? `<button class="btn-msg-action" onclick="window.editMessage('${msg.id}')" title="Edit and resubmit">✏️ Edit</button>` : `<button class="btn-msg-action" onclick="window.regenerateLast()" title="Regenerate assistant response">🔄 Regenerate</button>`}
        <div class="msg-overflow-wrapper">
          <button class="btn-msg-action" data-overflow-trigger title="More actions">⋯ More</button>
          <div class="msg-overflow-menu">
            <button onclick="window.branchFromMessage('${msg.id}')">🌿 Branch here</button>
            ${!isUser ? `<button data-compare-msg="${msg.id}">⚖️ Compare models</button>` : ''}
            <button class="danger" onclick="window.deleteMsg('${msg.id}')">🗑️ Delete message</button>
          </div>
        </div>
      </div>
    </div>
  `;

  return row;
}


// ==========================================
// SENDING & AGENT STREAMING
// ==========================================

async function sendMessage() {
  const text = DOM.composerTextarea.value.trim();
  if (!text && state.activeAttachments.length === 0) return;
  if (state.isStreaming) return;

  // Intercept slash commands: they never touch the model.
  if (text.startsWith("/") && !text.startsWith("//")) {
    const handled = await handleSlashCommand(text);
    if (handled) {
      DOM.composerTextarea.value = "";
      DOM.composerTextarea.style.height = "auto";
      return;
    }
  }

  if (!state.currentConversationId) {
    await createNewConversation(state.activeProjectFilter);
  }

  const convId = state.currentConversationId;
  const attachmentsToSend = [...state.activeAttachments];

  clearDraft(convId);
  DOM.composerTextarea.value = "";
  DOM.composerTextarea.style.height = "auto";
  state.activeAttachments = [];
  renderAttachmentChips();

  // Optimistic User Row
  DOM.messagesViewport.appendChild(createMessageRow({
    id: "temp-" + Date.now(),
    role: "user",
    content: text,
    attachments: attachmentsToSend,
    created_at: new Date().toISOString()
  }));

  // Assistant Streaming Row
  const streamModel = DOM.modelSelector.value || "assistant";
  const aiRow = document.createElement("div");
  aiRow.className = "message-row assistant";
  aiRow.innerHTML = `
    <div class="message-avatar ai">${escapeHtml(getModelAvatarLabel(streamModel))}</div>
    <div class="message-body">
      <div class="message-header-info">
        <span>${escapeHtml(getModelDisplayName(streamModel))}</span>
        <span class="token-speed-tag" id="liveSpeedTag">Generating...</span>
      </div>
      <div id="liveThinkContainer"></div>
      <div id="liveToolContainer"></div>
      <div class="message-content" id="liveStreamContent"></div>
      <div id="liveCitationContainer"></div>
    </div>
  `;
  DOM.messagesViewport.appendChild(aiRow);
  scrollToBottom();

  setStreamingState(true);
  state.currentAbortController = new AbortController();

  const liveContentEl = document.getElementById("liveStreamContent");
  const liveSpeedTag = document.getElementById("liveSpeedTag");
  const liveToolContainer = document.getElementById("liveToolContainer");
  const liveThinkContainer = document.getElementById("liveThinkContainer");
  const liveCitationContainer = document.getElementById("liveCitationContainer");

  let accumulated = "";
  let thinkAccumulated = "";
  let inThinkBlock = false;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: state.currentAbortController.signal,
      body: JSON.stringify({
        conversation_id: convId,
        message: text,
        model: DOM.modelSelector.value || "qwen2.5:32b",
        enable_web_search: state.tools.webSearch,
        enable_code_execution: state.tools.codeExecution,
        think_deeply: state.tools.thinkDeeply,
        attachments: attachmentsToSend
      })
    });

    if (!response.ok) throw new Error(`Server returned HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop();

      for (const block of blocks) {
        if (!block.trim()) continue;

        let eventType = "message";
        let dataStr = "";

        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) eventType = line.substring(7).trim();
          if (line.startsWith("data: ")) dataStr = line.substring(6).trim();
        }

        if (eventType === "token") {
          const parsed = JSON.parse(dataStr);
          const delta = parsed.delta;

          // Route think-block tokens separately
          if (delta.includes("<think>")) inThinkBlock = true;
          if (inThinkBlock) {
            thinkAccumulated += delta;
            if (delta.includes("</think>")) {
              inThinkBlock = false;
              const thinkContent = thinkAccumulated.replace(/<\/?think>/g, "").trim();
              liveThinkContainer.innerHTML = `
                <details class="think-block" open>
                  <summary>🧠 Reasoning (${thinkContent.split(/\s+/).length} words)</summary>
                  <div class="think-content">${escapeHtml(thinkContent)}</div>
                </details>`;
              thinkAccumulated = "";
            }
          } else {
            accumulated += delta;
            liveContentEl.innerHTML = parseMarkdown(accumulated);
          }
          scrollToBottom();
        } else if (eventType === "tool_start") {
          const parsed = JSON.parse(dataStr);
          liveToolContainer.innerHTML += `
            <div class="tool-execution-card">
              <div class="tool-card-header">
                <span>🌐 ${escapeHtml(parsed.title || parsed.tool)}: <em>"${escapeHtml(parsed.query || '')}"</em></span>
                <span class="tool-status-pill running">Searching...</span>
              </div>
            </div>
          `;
        } else if (eventType === "tool_end") {
          const parsed = JSON.parse(dataStr);
          liveToolContainer.innerHTML = createToolCardHtml(parsed.tool, parsed.status, parsed.result);
        } else if (eventType === "citation") {
          const parsed = JSON.parse(dataStr);
          liveCitationContainer.innerHTML += createCitationCardHtml([parsed]);
        } else if (eventType === "retrieval_debug") {
          const parsed = JSON.parse(dataStr);
          const rows = (parsed.hits || []).map((h, i) => `
            <tr>
              <td>${i + 1}</td>
              <td class="rag-filename">${escapeHtml(h.filename || '')} <span class="rag-chunk">·${h.chunk_index}</span></td>
              <td>${h.fused_score != null ? Number(h.fused_score).toFixed(4) : '-'}</td>
              <td>${h.rerank_score != null ? Number(h.rerank_score).toFixed(1) : '-'}</td>
              <td>${h.vector_rank ?? '-'}</td>
              <td>${h.bm25_rank ?? '-'}</td>
            </tr>
          `).join('');
          const wc = (parsed.hits || []).length;
          liveToolContainer.innerHTML += `
            <details class="rag-debug-panel">
              <summary>🔍 Retrieval details (${wc} chunks)</summary>
              <table class="rag-debug-table">
                <thead><tr><th>#</th><th>Source</th><th>Fused</th><th>Rerank</th><th>Vec rank</th><th>BM25 rank</th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </details>`;
        } else if (eventType === "artifact_created") {
          const parsed = JSON.parse(dataStr);
          openArtifactDrawer(parsed);
        } else if (eventType === "thinking_phase") {
          const parsed = JSON.parse(dataStr);
          const label = escapeHtml(parsed.label || parsed.phase || "thinking");
          liveToolContainer.innerHTML += `<div class="tool-execution-card"><div class="tool-card-header"><span>🧠 ${label}</span><span class="tool-status-pill running">running</span></div></div>`;
        } else if (eventType === "critique") {
          const parsed = JSON.parse(dataStr);
          const wc = (parsed.text || "").trim().split(/\s+/).length;
          liveToolContainer.innerHTML += `<details class="think-block"><summary>🔍 Reviewer critique (${wc} words)</summary><div class="think-content">${escapeHtml(parsed.text || "")}</div></details>`;
        } else if (eventType === "revision_start") {
          accumulated = "";
          liveContentEl.innerHTML = "";
        } else if (eventType === "grounding_check") {
          const parsed = JSON.parse(dataStr);
          if (parsed.status === "success") {
            const pct = Math.round(parsed.coverage * 100);
            const badgeClass = pct >= 80 ? "ok" : (pct >= 50 ? "warn" : "err");
            const unsupported = (parsed.sentences || []).filter(s => !s.supported);
            const detailRows = unsupported.map(s =>
              `<li>${escapeHtml(s.sentence)} <span class="grounding-sim">(sim ${s.max_similarity})</span></li>`
            ).join('');
            liveToolContainer.innerHTML += `
              <details class="grounding-panel">
                <summary>
                  <span class="grounding-badge ${badgeClass}">${pct}% grounded</span>
                  <span class="grounding-meta">${parsed.supported}/${parsed.total} sentences supported by retrieved sources</span>
                </summary>
                ${unsupported.length ? `<div class="grounding-body"><strong>Potentially unsupported:</strong><ul>${detailRows}</ul></div>` : `<div class="grounding-body">All sentences supported by retrieved chunks. ✓</div>`}
              </details>`;
          }
        } else if (eventType === "done") {
          const parsed = JSON.parse(dataStr);
          liveSpeedTag.innerText = `⚡ ${parsed.token_count} tokens (${parsed.eval_tps} tok/s)`;
          refreshConversations();
        } else if (eventType === "error") {
          const parsed = JSON.parse(dataStr);
          liveContentEl.innerHTML += `
            <div style="color:var(--accent-rose); margin-top:8px;">
              ⚠️ ${escapeHtml(parsed.error)}
              <button class="tool-toggle-btn" style="margin-left:8px;" onclick="window.regenerateLast()">🔄 Retry Generation</button>
            </div>
          `;
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      liveContentEl.innerHTML += `<div style="color:var(--text-muted); margin-top:8px;">[Generation stopped by user]</div>`;
    } else {
      liveContentEl.innerHTML += `
        <div style="color:var(--accent-rose); margin-top:8px;">
          ⚠️ Error: ${escapeHtml(err.message)}
          <button class="tool-toggle-btn" style="margin-left:8px;" onclick="window.regenerateLast()">🔄 Retry Generation</button>
        </div>
      `;
    }
  } finally {
    setStreamingState(false);
    state.currentAbortController = null;
    selectConversation(convId);
  }
}

function stopGeneration() {
  if (state.currentAbortController) state.currentAbortController.abort();
}

/** Viewport-aware sidebar toggle.
 *  ≥900 px  → `.collapsed` (icon rail / hidden depending on breakpoint CSS)
 *  <900 px  → `.mobile-open` slide-in drawer, with a click-away scrim. */
function toggleSidebar() {
  if (!DOM.sidebar) return;
  const narrow = window.matchMedia("(max-width: 899px)").matches;
  if (narrow) {
    const nowOpen = !DOM.sidebar.classList.contains("mobile-open");
    DOM.sidebar.classList.toggle("mobile-open", nowOpen);
    toggleScrim(nowOpen);
  } else {
    DOM.sidebar.classList.toggle("collapsed");
  }
}

function toggleScrim(show) {
  let scrim = document.getElementById("sidebarScrim");
  if (!scrim && show) {
    scrim = document.createElement("div");
    scrim.id = "sidebarScrim";
    scrim.className = "sidebar-scrim";
    scrim.addEventListener("click", () => toggleSidebar());
    document.body.appendChild(scrim);
    requestAnimationFrame(() => scrim.classList.add("visible"));
    return;
  }
  if (scrim && !show) {
    scrim.classList.remove("visible");
    scrim.addEventListener("transitionend", () => scrim.remove(), { once: true });
  }
}

function setStreamingState(streaming) {
  state.isStreaming = streaming;
  DOM.btnSendMessage.style.display = streaming ? "none" : "flex";
  DOM.btnStopStream.style.display = streaming ? "flex" : "none";
  DOM.composerTextarea.disabled = streaming;
  announceToScreenReader(streaming ? "Generating response" : "Response ready");
}

/** Push a message into the `aria-live` region for screen readers.
 *  Cleared shortly after so it doesn't clutter the a11y tree. */
function announceToScreenReader(msg) {
  const el = document.getElementById("a11yLive");
  if (!el) return;
  el.textContent = "";
  // A microtask delay ensures the change is announced even for
  // identical consecutive messages.
  setTimeout(() => { el.textContent = msg; }, 30);
  setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
}


// ==========================================
// ARTIFACT DRAWER
// ==========================================

function openArtifactDrawer(artifact) {
  if (!DOM.artifactDrawer) return;
  DOM.artifactDrawer.classList.add("open");
  renderArtifactDrawer(artifact, DOM.artifactDrawer);
}

window.closeArtifactDrawer = function() {
  if (DOM.artifactDrawer) DOM.artifactDrawer.classList.remove("open");
};


// ==========================================
// FILE UPLOADS & ATTACHMENTS
// ==========================================

async function uploadFile(file) {
  const build = () => {
    const fd = new FormData();
    fd.append("file", file);
    if (state.currentConversationId) fd.append("conversation_id", state.currentConversationId);
    return fd;
  };

  try {
    const data = await withRetry(() => api.uploadFile(build()), { tries: 3, baseMs: 500 });
    if (data.status === "success") {
      state.activeAttachments.push(data.file);
      renderAttachmentChips();
    } else if (data.error) {
      throw new Error(data.error);
    }
  } catch (err) {
    showBanner({
      key: `upload-fail-${file.name}`,
      tone: "error",
      message: `Upload failed for <code>${escapeHtml(file.name)}</code>: ${escapeHtml(String(err.message || err))}`,
      actions: [{ label: "Retry", onClick: () => uploadFile(file) }],
    });
  }
}

function handleFileInputChange(e) {
  for (const f of e.target.files) uploadFile(f);
  DOM.fileInput.value = "";
}

async function handleProjectFileInputChange(e) {
  if (!state.activeProjectFilter) return;
  for (const file of e.target.files) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("project_id", state.activeProjectFilter);
    try {
      await api.uploadFile(formData);
    } catch (err) {
      alert("Project file upload failed: " + err.message);
    }
  }
  DOM.projectFileInput.value = "";
  if (state.currentConversationId) selectConversation(state.currentConversationId);
  else refreshConversations();
}

function handleFileDrop(e) {
  e.preventDefault();
  DOM.dragOverlay?.classList.remove("active");
  for (const f of e.dataTransfer.files) uploadFile(f);
}

function handleClipboardPaste(e) {
  const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
  if (!items) return;
  for (const item of items) {
    if (item.kind === "file") {
      uploadFile(item.getAsFile());
    }
  }
}

function renderAttachmentChips() {
  DOM.attachmentStrip.innerHTML = "";
  state.activeAttachments.forEach((att, idx) => {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    const isImage = (att.mime_type && att.mime_type.startsWith("image/")) ||
                    /\.(png|jpe?g|webp|gif|bmp)$/i.test(att.filename || "");
    const previewHtml = isImage && att.id ?
      `<img src="/api/files/${att.id}" class="attachment-thumb" alt="${escapeHtml(att.filename)}" />` :
      `<span>📄</span>`;

    chip.innerHTML = `
      ${previewHtml}
      <span>${escapeHtml(att.filename)}</span>
      <button class="btn-remove-att" onclick="window.removeAttachment(${idx})" title="Remove attachment">✕</button>
    `;
    DOM.attachmentStrip.appendChild(chip);
  });
}

window.removeAttachment = function(idx) {
  state.activeAttachments.splice(idx, 1);
  renderAttachmentChips();
};


// ==========================================
// CONTEXT MENUS & ACTIONS
// ==========================================

function showConversationContextMenu(e, conv) {
  const isPinned = conv.pinned === 1;
  const isArchived = conv.archived === 1;

  DOM.contextMenu.innerHTML = `
    <div class="context-menu-item" onclick="window.renameConv('${conv.id}', '${escapeHtml(conv.title)}')">✏️ Rename</div>
    <div class="context-menu-item" onclick="window.togglePin('${conv.id}', ${isPinned ? 0 : 1})">📌 ${isPinned ? 'Unpin' : 'Pin'} Chat</div>
    <div class="context-menu-item" onclick="window.toggleArchive('${conv.id}', ${isArchived ? 0 : 1})">📦 ${isArchived ? 'Unarchive' : 'Archive'} Chat</div>
    <div class="context-menu-item" onclick="window.openMoveProjectModal('${conv.id}')">📁 Move to Workspace...</div>
    <div class="context-menu-item" onclick="window.dupConv('${conv.id}')">📋 Duplicate</div>
    <div class="context-menu-item" onclick="window.exportConv('${conv.id}')">💾 Export Markdown</div>
    <div class="context-menu-item danger" onclick="window.delConv('${conv.id}')">🗑️ Delete</div>
  `;
  positionContextMenu(e);
}

function showProjectContextMenu(e, proj) {
  DOM.contextMenu.innerHTML = `
    <div class="context-menu-item" onclick="window.editProj('${proj.id}')">✏️ Edit Workspace</div>
    <div class="context-menu-item danger" onclick="window.delProj('${proj.id}')">🗑️ Delete Workspace</div>
  `;
  positionContextMenu(e);
}

function positionContextMenu(e) {
  DOM.contextMenu.style.display = "flex";
  DOM.contextMenu.style.top = `${Math.min(e.clientY, window.innerHeight - 240)}px`;
  DOM.contextMenu.style.left = `${Math.min(e.clientX, window.innerWidth - 220)}px`;
}

function hideContextMenu() {
  DOM.contextMenu.style.display = "none";
}

window.renameConv = async (id, title) => {
  const nt = prompt("New title:", title);
  if (nt && nt.trim()) {
    await api.updateConversation(id, { title: nt.trim() });
    refreshConversations();
    if (state.currentConversationId === id) DOM.chatTitle.innerText = nt.trim();
  }
};

window.togglePin = async (id, pinState) => {
  await api.updateConversation(id, { pinned: pinState });
  refreshConversations();
};

window.toggleArchive = async (id, archiveState) => {
  await api.updateConversation(id, { archived: archiveState });
  await refreshConversations();
  if (state.currentConversationId === id && archiveState === 1) {
    const active = state.conversations.filter(c => !c.archived);
    if (active.length > 0) selectConversation(active[0].id);
    else createNewConversation();
  }
};

window.openMoveProjectModal = (convId) => {
  DOM.moveTargetConvId.value = convId;
  DOM.moveProjectSelect.innerHTML = `<option value="">-- No Project (Root Workspace) --</option>`;
  state.projects.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.innerText = `${p.icon || '📁'} ${p.name}`;
    DOM.moveProjectSelect.appendChild(opt);
  });
  DOM.moveProjectModal.classList.add("open");
};

async function handleConfirmMoveProject() {
  const convId = DOM.moveTargetConvId.value;
  const projId = DOM.moveProjectSelect.value || null;
  if (convId) {
    await api.updateConversation(convId, { project_id: projId });
    closeAllModals();
    await refreshProjects();
    await refreshConversations();
    if (state.currentConversationId === convId) selectConversation(convId);
  }
}

window.branchFromMessage = async (msgId) => {
  if (!state.currentConversationId) return;
  const res = await api.branchConversation(state.currentConversationId, msgId);
  if (res.status === "success") {
    await refreshConversations();
    selectConversation(res.conversation.id);
    showToast("Branched into new conversation!");
  }
};

window.dupConv = async (id) => {
  const res = await api.duplicateConversation(id);
  if (res.status === "success") {
    await refreshConversations();
    selectConversation(res.conversation.id);
  }
};

window.delConv = async (id) => {
  if (confirm("Delete this conversation permanently?")) {
    await api.deleteConversation(id);
    await refreshConversations();
    if (state.currentConversationId === id) {
      if (state.conversations.length > 0) selectConversation(state.conversations[0].id);
      else createNewConversation();
    }
  }
};

window.exportConv = async (id) => {
  const res = await api.getConversation(id);
  if (res.status === "success") {
    let md = `# ${res.conversation.title}\n\n`;
    (res.conversation.messages || []).forEach(m => {
      md += `### ${m.role === 'user' ? 'User' : 'Assistant'}\n\n${m.content}\n\n`;
    });
    const blob = new Blob([md], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${res.conversation.title.replace(/[^a-zA-Z0-9]/g, "_")}.md`;
    a.click();
  }
};

window.deleteMsg = async (id) => {
  if (confirm("Delete this message?")) {
    await api.deleteMessage(id);
    if (state.currentConversationId) selectConversation(state.currentConversationId);
  }
};

window.copyMessage = (id) => {
  const row = document.querySelector(`.message-row[data-id="${id}"]`);
  if (row) {
    navigator.clipboard.writeText(row.querySelector(".message-content").innerText);
    showToast("Message copied to clipboard!");
  }
};

window.editMessage = (id) => {
  const row = document.querySelector(`.message-row[data-id="${id}"]`);
  if (row) {
    DOM.composerTextarea.value = row.querySelector(".message-content").innerText;
    autoResizeComposer();
    DOM.composerTextarea.focus();
    window.deleteMsg(id);
  }
};

const PROMPT_TEMPLATES = [
  { category: "Security", title: "Threat model this design",
    body: "Threat-model the following system. For each component list: assets → threats (STRIDE) → likelihood → impact → concrete mitigations. Cite OWASP or MITRE ATT&CK IDs where they apply.\n\n<PASTE DESIGN OR CODE HERE>" },
  { category: "Security", title: "Audit this code for vulnerabilities",
    body: "Audit this code for security vulnerabilities. Prioritize by exploitability. For each finding: CWE ID, description, exploit scenario, fix, and a test that would catch it.\n\n```\n<PASTE CODE>\n```" },
  { category: "Security", title: "Explain a CVE",
    body: "Explain CVE-<NUMBER> in depth: root cause, exploit path, affected versions, mitigations, detection signatures. Cite the primary references." },
  { category: "Coding", title: "Refactor with tests",
    body: "Refactor this code for clarity and correctness. Add type hints. Then write pytest tests covering the happy path + 3 edge cases.\n\n```\n<PASTE CODE>\n```" },
  { category: "Coding", title: "Explain step-by-step",
    body: "Explain this code line-by-line. Highlight non-obvious behavior, potential bugs, and simpler alternatives.\n\n```\n<PASTE CODE>\n```" },
  { category: "Coding", title: "Design an API",
    body: "Design a REST/HTTP API for <FEATURE>. Cover: resource model, endpoints (method + path + auth), request/response schemas, error handling, versioning, rate-limit strategy. Show OpenAPI YAML for the top 3 endpoints." },
  { category: "Coding", title: "Debug this error",
    body: "I hit this error. What's the likely root cause and how do I fix it? Give the smallest reproduction I could bisect against.\n\n```\n<PASTE ERROR / TRACEBACK>\n```" },
  { category: "Research", title: "Deep dive on a topic",
    body: "Give me a technical deep-dive on <TOPIC>. Structure: 1) what it is, 2) why it exists, 3) how it works internally, 4) trade-offs vs alternatives, 5) real-world examples, 6) further reading (papers + docs)." },
  { category: "Research", title: "Compare N options",
    body: "Compare <A> vs <B> vs <C> for <USE CASE>. For each: strengths, weaknesses, when to pick it. Include a decision matrix." },
  { category: "Meta", title: "Rewrite this prompt to be better",
    body: "Rewrite the following prompt to be more specific and effective. Return the improved prompt only.\n\nOriginal: <PASTE PROMPT>" },
];

function openPromptTemplates() {
  const byCategory = PROMPT_TEMPLATES.reduce((m, t) => {
    (m[t.category] = m[t.category] || []).push(t);
    return m;
  }, {});
  const html = Object.entries(byCategory).map(([cat, items]) => `
    <div class="template-cat"><h4>${escapeHtml(cat)}</h4>
      ${items.map((t, i) => `
        <div class="template-item" data-template-i="${PROMPT_TEMPLATES.indexOf(t)}">
          <div class="template-title">${escapeHtml(t.title)}</div>
          <div class="template-preview">${escapeHtml(t.body.slice(0, 120))}...</div>
        </div>
      `).join('')}
    </div>`).join('');
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop show";
  overlay.innerHTML = `
    <div class="modal-window" style="max-width: 720px;">
      <div class="modal-header">
        <h3>📝 Prompt Templates</h3>
        <button class="btn-icon" data-tpl-close>✕</button>
      </div>
      <div class="modal-body">
        <div class="template-list">${html}</div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelectorAll("[data-tpl-close]").forEach(el =>
    el.addEventListener("click", () => overlay.remove()));
  overlay.querySelectorAll(".template-item").forEach(el => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.getAttribute("data-template-i"), 10);
      const tpl = PROMPT_TEMPLATES[idx];
      if (!tpl) return;
      DOM.composerTextarea.value = tpl.body;
      DOM.composerTextarea.focus();
      DOM.composerTextarea.dispatchEvent(new Event("input", { bubbles: true }));
      overlay.remove();
    });
  });
}
window.openPromptTemplates = openPromptTemplates;


function installTooltips(root) {
  const els = root.querySelectorAll ? root.querySelectorAll("[title]") : [];
  els.forEach(el => {
    const t = el.getAttribute("title");
    if (!t) return;
    // Move title → data-tooltip so browser doesn't ALSO show its native tooltip
    if (!el.hasAttribute("data-tooltip")) el.setAttribute("data-tooltip", t);
    el.removeAttribute("title");
  });
}
window.installTooltips = installTooltips;


async function handleSlashCommand(raw) {
  const parts = raw.slice(1).trim().split(/\s+/);
  const cmd = (parts[0] || "").toLowerCase();
  const rest = parts.slice(1).join(" ");
  switch (cmd) {
    case "help":
    case "?":
      showToast("Commands: /model <name> · /workspace <name> · /new · /clear · /templates · /settings · /help");
      return true;
    case "model": {
      if (!rest) { showToast("usage: /model <name-or-fragment>"); return true; }
      const match = (state.models || []).find(m => m.name === rest)
        || (state.models || []).find(m => m.name.includes(rest));
      if (!match) { showToast(`No installed model matching "${rest}"`); return true; }
      if (DOM.modelSelector) DOM.modelSelector.value = match.name;
      showToast(`Model → ${match.name}`);
      return true;
    }
    case "workspace":
    case "ws": {
      if (!rest) { showToast("usage: /workspace <name-fragment>"); return true; }
      const q = rest.toLowerCase();
      const match = (state.projects || []).find(p => p.name.toLowerCase().includes(q));
      if (!match) { showToast(`No workspace matching "${rest}"`); return true; }
      state.activeProjectFilter = match.id;
      await refreshProjects();
      await refreshConversations();
      showToast(`Workspace → ${match.name}`);
      return true;
    }
    case "new":
      await createNewConversation(state.activeProjectFilter);
      return true;
    case "clear":
      if (state.currentConversationId && confirm("Delete current conversation?")) {
        await api.deleteConversation(state.currentConversationId);
        await refreshConversations();
        await createNewConversation(state.activeProjectFilter);
      }
      return true;
    case "templates":
    case "tpl":
      openPromptTemplates();
      return true;
    case "settings":
      openSettingsModal();
      return true;
    default:
      return false;  // unknown command — fall through to normal send
  }
}
window.handleSlashCommand = handleSlashCommand;


function openCompareModal(prompt, defaultModelA) {
  const modelOptions = Array.from(DOM.modelSelector?.options || [])
    .map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.text)}</option>`).join('');
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop show";
  overlay.innerHTML = `
    <div class="modal-window" style="max-width: 1000px; width: 92vw;">
      <div class="modal-header">
        <h3>⚖️ Compare Models</h3>
        <button class="btn-icon" data-compare-close>✕</button>
      </div>
      <div class="modal-body">
        <div class="form-field">
          <label>Prompt</label>
          <textarea class="form-textarea" rows="3" id="compareInput">${escapeHtml(prompt)}</textarea>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
          <div class="form-field"><label>Model A</label><select class="form-select" id="compareModelA">${modelOptions}</select></div>
          <div class="form-field"><label>Model B</label><select class="form-select" id="compareModelB">${modelOptions}</select></div>
        </div>
        <div id="compareResults" style="margin-top: 14px;"></div>
      </div>
      <div class="modal-footer">
        <button class="tool-toggle-btn" data-compare-close>Close</button>
        <button class="btn-send-message" id="btnCompareRun">Run comparison</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const modelA = overlay.querySelector("#compareModelA");
  const modelB = overlay.querySelector("#compareModelB");
  modelA.value = defaultModelA;
  // Pick a different default for B
  const opts = Array.from(modelB.options).map(o => o.value);
  modelB.value = opts.find(v => v !== defaultModelA && !v.includes("nomic-embed")) || defaultModelA;

  overlay.querySelectorAll("[data-compare-close]").forEach(el =>
    el.addEventListener("click", () => overlay.remove()));

  overlay.querySelector("#btnCompareRun").addEventListener("click", async () => {
    const prompt = overlay.querySelector("#compareInput").value.trim();
    if (!prompt) return;
    const results = overlay.querySelector("#compareResults");
    results.innerHTML = `<div class="compare-loading">Running both models in parallel...</div>`;
    try {
      const r = await fetch("/api/chat/compare", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: prompt, model_a: modelA.value, model_b: modelB.value }),
      });
      const data = await r.json();
      const card = (side, res) => `
        <div class="compare-col">
          <div class="compare-col-header">
            <strong>${side === 'a' ? 'A' : 'B'}: ${escapeHtml(res.model)}</strong>
            ${res.tokens ? `<span class="token-speed-tag">⚡ ${res.tokens} tok · ${res.tps} tok/s</span>` : ''}
          </div>
          <div class="compare-col-body">${res.status === 'error' ? `<div class="code-run-err">${escapeHtml(res.error||'')}</div>` : parseMarkdown(res.content || '')}</div>
        </div>`;
      results.innerHTML = `<div class="compare-grid">${card('a', data.a)}${card('b', data.b)}</div>`;
    } catch (err) {
      results.innerHTML = `<div class="code-run-err">Compare failed: ${escapeHtml(String(err))}</div>`;
    }
  });
}
window.openCompareModal = openCompareModal;


window.regenerateLast = () => {
  if (!state.currentConversation?.messages) return;
  const userMsgs = state.currentConversation.messages.filter(m => m.role === "user");
  if (userMsgs.length === 0) return;
  DOM.composerTextarea.value = userMsgs[userMsgs.length - 1].content;
  sendMessage();
};


// ==========================================
// PROJECT WORKSPACE MANAGEMENT
// ==========================================

window.openNewProjectModal = function(projId = null) {
  if (projId) {
    const p = state.projects.find(x => x.id === projId);
    if (p) {
      DOM.projectModalTitle.innerText = "Edit Workspace";
      DOM.editingProjectId.value = p.id;
      DOM.projectNameInput.value = p.name;
      DOM.projectDescInput.value = p.description || "";
      DOM.projectInstructionsInput.value = p.system_instructions || "";
    }
  } else {
    DOM.projectModalTitle.innerText = "Create New Workspace";
    DOM.editingProjectId.value = "";
    DOM.projectNameInput.value = "";
    DOM.projectDescInput.value = "";
    DOM.projectInstructionsInput.value = "";
  }
  DOM.projectModal.classList.add("open");
  setTimeout(() => DOM.projectNameInput.focus(), 100);
};

window.editProj = function(id) {
  window.openNewProjectModal(id);
};

window.delProj = async function(id) {
  if (confirm("Delete this workspace and unassign its conversations?")) {
    await api.deleteProject(id);
    if (state.activeProjectFilter === id) state.activeProjectFilter = null;
    await refreshProjects();
    await refreshConversations();
  }
};

async function handleSaveProject() {
  const name = DOM.projectNameInput.value.trim();
  if (!name) return alert("Please enter a workspace name");

  const payload = {
    name: name,
    description: DOM.projectDescInput.value.trim(),
    system_instructions: DOM.projectInstructionsInput.value.trim()
  };

  const editId = DOM.editingProjectId.value;
  if (editId) {
    await api.updateProject(editId, payload);
  } else {
    const res = await api.createProject(payload);
    if (res.status === "success") {
      state.activeProjectFilter = res.project.id;
    }
  }

  closeAllModals();
  await refreshProjects();
  await refreshConversations();
  if (state.activeProjectFilter && state.currentConversationId) {
    selectConversation(state.currentConversationId);
  }
}

window.deleteProjectFile = async function(fileId) {
  if (confirm("Remove this file from the workspace?")) {
    await api.deleteFile(fileId);
    if (state.currentConversationId) selectConversation(state.currentConversationId);
    else refreshConversations();
  }
};


// ==========================================
// SEARCH MODAL (Ctrl+K)
// ==========================================

function openSearchModal() {
  DOM.searchModal.classList.add("open");
  DOM.searchModalInput.value = "";
  DOM.searchResultsList.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:20px;">Type to search messages, projects, and files...</div>`;
  setTimeout(() => DOM.searchModalInput.focus(), 100);
}

async function handleGlobalSearch() {
  const q = DOM.searchModalInput.value.trim();
  if (!q) {
    DOM.searchResultsList.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:20px;">Type to search messages · '>' for commands · '?' for help</div>`;
    return;
  }
  // Command mode: '>' prefix
  if (q.startsWith(">") || q === "?") {
    renderCommandPalette(q.startsWith(">") ? q.slice(1).trim() : "");
    return;
  }
  const data = await api.search(q);
  if (data.status === "success") {
    renderSearchResults(data.results);
  }
}

function _paletteCommands() {
  const cmds = [
    { name: "help", label: "❔ Help — show all commands", run: () => renderCommandPalette("") },
    { name: "new", label: "＋ New conversation", run: () => { closeAllModals(); createNewConversation(state.activeProjectFilter); } },
    { name: "settings", label: "⚙️  Open settings", run: () => { closeAllModals(); openSettingsModal(); } },
    { name: "templates", label: "📝 Prompt templates", run: () => { closeAllModals(); openPromptTemplates(); } },
    { name: "toggle sidebar", label: "🔀 Toggle sidebar", run: () => { closeAllModals(); DOM.sidebar?.classList.toggle("collapsed"); } },
  ];
  // Model switches
  (state.models || []).forEach(m => {
    cmds.push({
      name: `model ${m.name}`,
      label: `🤖 Switch model → ${m.name}`,
      run: () => {
        closeAllModals();
        if (DOM.modelSelector) DOM.modelSelector.value = m.name;
        showToast(`Model → ${m.name}`);
      },
    });
  });
  // Workspace jumps
  (state.projects || []).forEach(p => {
    cmds.push({
      name: `workspace ${p.name}`,
      label: `📁 Jump to workspace → ${p.name}`,
      run: () => {
        closeAllModals();
        state.activeProjectFilter = p.id;
        refreshProjects();
        refreshConversations();
      },
    });
  });
  return cmds;
}

function renderCommandPalette(query) {
  const all = _paletteCommands();
  const q = query.toLowerCase();
  const matched = q
    ? all.filter(c => c.name.toLowerCase().includes(q) || c.label.toLowerCase().includes(q))
    : all;
  DOM.searchResultsList.innerHTML = "";
  matched.forEach(cmd => {
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.innerHTML = `<span class="result-badge">Command</span><span class="result-title">${escapeHtml(cmd.label)}</span>`;
    item.onclick = () => cmd.run();
    DOM.searchResultsList.appendChild(item);
  });
  if (matched.length === 0) {
    DOM.searchResultsList.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:20px;">No commands match "${escapeHtml(query)}".</div>`;
  }
}

function renderSearchResults(results) {
  DOM.searchResultsList.innerHTML = "";
  let total = 0;

  (results.conversations || []).forEach(c => {
    total++;
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.innerHTML = `<span class="result-badge">Conversation</span><span class="result-title">${escapeHtml(c.title)}</span>`;
    item.onclick = () => {
      closeAllModals();
      selectConversation(c.id);
    };
    DOM.searchResultsList.appendChild(item);
  });

  (results.messages || []).forEach(m => {
    total++;
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.innerHTML = `<span class="result-badge">Message in "${escapeHtml(m.conversation_title)}"</span><span class="result-snippet">${escapeHtml(m.content)}</span>`;
    item.onclick = () => {
      closeAllModals();
      selectConversation(m.conversation_id);
    };
    DOM.searchResultsList.appendChild(item);
  });

  if (total === 0) {
    DOM.searchResultsList.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:20px;">No results found.</div>`;
  }
}


// ==========================================
// SETTINGS & BACKUP/RESTORE
// ==========================================

function openSettingsModal() {
  // Sync the settings model dropdown with whatever models are loaded
  const settingsSel = document.getElementById("settingDefaultModel");
  if (settingsSel && DOM.modelSelector) {
    settingsSel.innerHTML = DOM.modelSelector.innerHTML;
  }
  const savedModel = state.settings.default_model || "";
  if (settingsSel && savedModel) settingsSel.value = savedModel;

  document.getElementById("settingTemp").value = state.settings.default_temperature || "0.7";
  document.getElementById("settingSystemPrompt").value = state.settings.system_prompt || "";
  DOM.settingsModal.classList.add("open");
}

window.openSettingsModal = openSettingsModal;

window.saveSettingsFromModal = async function() {
  const updated = {
    default_model: document.getElementById("settingDefaultModel").value,
    default_temperature: document.getElementById("settingTemp").value,
    system_prompt: document.getElementById("settingSystemPrompt").value
  };
  await api.saveSettings(updated);
  state.settings = { ...state.settings, ...updated };
  closeAllModals();
  showToast("Settings saved successfully!");
};

window.exportWorkspaceBackup = async function() {
  const data = await api.exportWorkspace();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `local_llm_studio_backup_${Date.now()}.json`;
  a.click();
};

window.importWorkspaceBackup = function() {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = ".json";
  inp.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (re) => {
      try {
        const json = JSON.parse(re.target.result);
        await api.importWorkspace(json);
        alert("Workspace backup restored successfully!");
        location.reload();
      } catch (err) {
        alert("Failed to parse backup JSON: " + err.message);
      }
    };
    reader.readAsText(file);
  };
  inp.click();
};


// ==========================================
// UTILITIES
// ==========================================

function autoResizeComposer() {
  DOM.composerTextarea.style.height = "auto";
  DOM.composerTextarea.style.height = Math.min(DOM.composerTextarea.scrollHeight, 240) + "px";
}

function scrollToBottom() {
  DOM.messagesViewport.scrollTop = DOM.messagesViewport.scrollHeight;
}

function closeAllModals() {
  document.querySelectorAll(".modal-backdrop").forEach(m => m.classList.remove("open"));
}
window.closeAllModals = closeAllModals;

function showToast(msg) {
  const toast = document.createElement("div");
  toast.className = "copy-toast";
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2200);
}

function debounce(func, wait) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

