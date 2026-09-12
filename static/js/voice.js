/**
 * Voice I/O — mic button (whisper) + 🔊 button on assistant messages
 * (piper). Both features hide themselves when
 * GET /api/audio/status reports the corresponding binary as absent.
 *
 * Mic UX:
 *   click        → getUserMedia + MediaRecorder starts, button turns red
 *   click again  → stop recording, POST audio to /api/audio/transcribe,
 *                  paste transcript into the composer at the cursor
 *   Esc          → cancel without transcribing
 *
 * TTS UX:
 *   click 🔊     → POST the assistant message to /api/audio/tts, play
 *                  the returned WAV in an <audio>
 *   click again  → pause / resume
 */

const CAPS = { transcribe: false, tts: false };

async function fetchCaps() {
  try {
    const r = await fetch("/api/audio/status", { credentials: "include" });
    if (!r.ok) return;
    const j = await r.json();
    CAPS.transcribe = !!j?.transcribe?.available;
    CAPS.tts = !!j?.tts?.available;
  } catch { /* status is best-effort */ }
}

// ── Mic button ───────────────────────────────────────────────────────

let recorder = null;
let chunks = [];
let stream = null;
let cancelled = false;

async function startRecording(btn) {
  cancelled = false;
  chunks = [];
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    btn.title = "Microphone permission denied";
    return;
  }
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  recorder.onstop = () => finishRecording(btn);
  recorder.start();
  btn.classList.add("recording");
  btn.setAttribute("aria-pressed", "true");
  document.addEventListener("keydown", escToCancel);
}

function escToCancel(e) {
  if (e.key !== "Escape" || !recorder) return;
  cancelled = true;
  stopStreamTracks();
  try { recorder.stop(); } catch {}
}

function stopStreamTracks() {
  if (stream) stream.getTracks().forEach(t => t.stop());
  stream = null;
}

async function finishRecording(btn) {
  document.removeEventListener("keydown", escToCancel);
  btn.classList.remove("recording");
  btn.setAttribute("aria-pressed", "false");
  const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
  recorder = null;
  stopStreamTracks();
  if (cancelled || blob.size === 0) return;

  const fd = new FormData();
  const ext = (blob.type || "").includes("mp4") ? ".m4a"
            : (blob.type || "").includes("ogg") ? ".ogg" : ".webm";
  fd.append("file", blob, `voice${ext}`);
  btn.title = "Transcribing…";
  try {
    const r = await fetch("/api/audio/transcribe", { method: "POST", body: fd, credentials: "include" });
    if (!r.ok) {
      btn.title = `Transcribe failed (${r.status})`;
      return;
    }
    const j = await r.json();
    insertIntoComposer(j.text || "");
    btn.title = "Voice input (whisper)";
  } catch (e) {
    btn.title = `Transcribe failed: ${e.message || e}`;
  }
}

function insertIntoComposer(text) {
  const ta = document.getElementById("composerTextarea");
  if (!ta || !text) return;
  const start = ta.selectionStart ?? ta.value.length;
  const end = ta.selectionEnd ?? ta.value.length;
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  const insertion = before && !before.endsWith(" ") ? " " + text : text;
  ta.value = before + insertion + after;
  const caret = (before + insertion).length;
  ta.setSelectionRange(caret, caret);
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  ta.focus();
}

function ensureMicButton() {
  if (!CAPS.transcribe) return;
  const composerTools = document.querySelector(".composer-left-tools");
  if (!composerTools || document.getElementById("btnMic")) return;
  const btn = document.createElement("button");
  btn.id = "btnMic";
  btn.className = "btn-icon";
  btn.title = "Voice input (whisper)";
  btn.setAttribute("aria-label", "Record voice input");
  btn.setAttribute("aria-pressed", "false");
  btn.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3"/>
      <path d="M5 10a7 7 0 0 0 14 0"/>
      <line x1="12" y1="19" x2="12" y2="22"/>
    </svg>`;
  btn.addEventListener("click", () => {
    if (recorder) { try { recorder.stop(); } catch {} }
    else startRecording(btn);
  });
  composerTools.appendChild(btn);
}

// ── TTS 🔊 button on assistant messages ───────────────────────────────

let ttsAudio = null;

async function playTts(text) {
  if (!text) return;
  if (ttsAudio && !ttsAudio.paused) { ttsAudio.pause(); return; }
  const r = await fetch("/api/audio/tts", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) return;
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  ttsAudio = new Audio(url);
  ttsAudio.play();
  ttsAudio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
}

/** Attach a 🔊 button to every rendered assistant message that hasn't
 *  got one yet. Called after each render pass. */
function decorateAssistantMessages() {
  if (!CAPS.tts) return;
  document.querySelectorAll("[data-role='assistant']:not([data-tts-wired])").forEach(el => {
    el.dataset.ttsWired = "1";
    const btn = document.createElement("button");
    btn.className = "btn-icon tts-btn";
    btn.title = "Speak this response";
    btn.setAttribute("aria-label", "Play response as audio");
    btn.textContent = "🔊";
    btn.addEventListener("click", () => {
      const txt = el.dataset.contentText || el.textContent || "";
      playTts(txt);
    });
    (el.querySelector(".message-actions") || el).appendChild(btn);
  });
}

// ── Public entry point ───────────────────────────────────────────────

export async function installVoiceFeatures() {
  await fetchCaps();
  ensureMicButton();
  decorateAssistantMessages();
  // Re-scan the DOM whenever a new message lands. MutationObserver is
  // cheaper than polling and precise enough for our redraw pattern.
  const obs = new MutationObserver(decorateAssistantMessages);
  const viewport = document.getElementById("messagesViewport");
  if (viewport) obs.observe(viewport, { childList: true, subtree: true });
}
