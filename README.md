# ⚡ Local LLM Studio: Extensible AI Operating Workspace

A production-quality local AI assistant platform running natively on your **Apple M4 Pro (37 GB unified memory)**. 100% private, 100% offline, zero cloud subscriptions, zero corporate refusal filters, with autonomous multi-step agent orchestration, first-class artifacts, citations, and strict security sandboxing.

> **Hardware note:** This project was originally built for a Windows RTX 3060 (6 GB). It has been fully upgraded for the Apple M4 Pro (37 GB unified memory) — you can now run 32B parameter models that are 4× more capable than what fit on the old machine.

---

## 💻 Hardware & System Specifications

| Component | Specification | Studio Role |
|---|---|---|
| **SoC** | Apple M4 Pro | Neural compute via Metal (MLX). All model weights live in unified memory. |
| **Unified Memory** | 37 GB (shared CPU + GPU) | Fits 32B models at Q4_K_M (~20 GB) with room to spare. 70B at Q3_K_M (~28 GB). |
| **CPU** | M4 Pro (12-core) | Tokenization, context compaction, subprocess management. |
| **OS** | macOS (Apple Silicon) | Native execution via Ollama + Python. No CUDA required. |
| **Inference Engine** | Ollama (Metal backend) | Automatic GPU offload via Apple Metal — no configuration needed. |

---

## 🏛️ Comprehensive System Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         MODULAR SPA FRONTEND (static/)                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐ │
│  │   state.js   │ │    api.js    │ │ markdown.js  │ │ agent_ui.js  │ │artifacts│ │
│  │(Central Store│ │(SSE & REST)  │ │(Rich Parser) │ │(Tool & Step) │ │  _ui.js │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └─────────┘ │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ REST + SSE (EventStream)
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                       WORKSPACE BACKEND (FastAPI / ASGI)                         │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 1. AGENT ORCHESTRATION LAYER (backend/agent_orchestrator.py)               │  │
│  │    • Multi-Step Execution Loop (User Request → Plan → Tool → Observe → Done)│  │
│  │    • Tool Registry with Strict JSON Schemas                                │  │
│  │    • Execution IDs, Timeouts (20s), Max Steps (5), Cancellation Token       │  │
│  │    • Human-in-the-Loop Approval Checkpoints                                │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 2. CONTEXT MANAGEMENT LAYER (backend/context_manager.py)                   │  │
│  │    • Token Counting & Budget Allocation                                    │  │
│  │    • Dynamic Context Compaction & Sliding Window                           │  │
│  │    • Conversation Summarization for long histories                         │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 3. ARTIFACT SYSTEM (backend/artifacts.py)                                  │  │
│  │    • First-class generated files (Code, Markdown, HTML, JSON, CSV)         │  │
│  │    • Versioning, In-Browser Preview, Editing, and Direct Download          │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 4. SECURITY & PERMISSIONS SANDBOX (backend/security.py)                    │  │
│  │    • Path traversal & symlink escape prevention (chroot to workspace)      │  │
│  │    • Python process resource limits & isolated temp folders                │  │
│  │    • Tool permissions matrix: [Disabled | Ask Before Use | Always Allow]   │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 5. MODEL CAPABILITIES REGISTRY (backend/model_capabilities.py)             │  │
│  │    • Dynamic capability profiles (Context Window, Vision, Tools, Coding)   │  │
│  │    • Vision validator (prevents sending images to text-only models)        │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 6. CITATIONS & DOCUMENT ENGINE (backend/citations.py)                      │  │
│  │    • Structured citation entities (URL, Title, Chunk Snippet, Relevance)   │  │
│  │    • Extensible Document Ingestion & Chunking (RAG-ready interface)        │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │ 7. PERSISTENCE LAYER (backend/database.py - SQLite WAL)                    │  │
│  │    • Tables: projects, conversations, messages, artifacts, citations, files│  │
│  │    • Full Workspace Backup & JSON Import/Export                            │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ Native REST
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│              LOCAL OLLAMA ENGINE (Apple M4 Pro · 37 GB unified)                  │
│   Qwen 2.5 32B / DeepSeek R1 32B / Hermes 3 / Dolphin 3 / LLaVA / Mistral       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Fast Start: Launch Your Studio

```bash
./start_web_ui.sh
```
Or manually:
```bash
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8080
```
Open your browser at: **[http://localhost:8080](http://localhost:8080)**

---

## 🌟 Key Features & Capabilities

### 1. Autonomous Multi-Step Agent Orchestrator
* Autonomous reasoning loops with `execution_id`, step limits (`max_steps = 8`), and cancel tokens.
* Live Web Search via DuckDuckGo without API keys.
* Python Sandbox for executing code and math locally with timeout protection.
* Interactive Collapsible Tool Cards and Citations.

### 2. First-Class Artifact System
* When the AI writes scripts, HTML documents, or reports, it outputs `<artifact>` tags.
* Artifacts slide out into a dedicated right-hand drawer with syntax-highlighted code and 1-click downloads.

### 3. Context Management & Token Compaction
* Prevents context overflows on long chats.
* Preserves system instructions and recent turns verbatim while automatically summarizing older turns into context blocks.

### 4. Security Sandbox & Permission Matrix
* Blocks path traversal (`../`) and verifies all file reads resolve strictly within the workspace.
* Configurable permission matrix per tool (`auto_allow`, `require_approval`, `disabled`).

### 5. Model Capability & Vision Validator
* Automatically detects model capabilities (context window, vision support, coding rating).
* Warns if images are attached to text-only models and suggests vision alternatives.

### 6. Workspace Backup, Export & Restore
* Download full JSON backup of all conversations, messages, projects, and artifacts.
* Restore backups with one click in the Settings modal (`Ctrl+,`).

---

## 📂 Project Directory Structure

```text
C:\Users\Amit\.gemini\antigravity\scratch\local-llm-studio\
│
├── backend\
│   ├── database.py              # SQLite persistence layer (WAL mode)
│   ├── agent_orchestrator.py    # Dedicated multi-step agent execution loop
│   ├── agent_tools.py           # Web search, Python sandbox, file explorer
│   ├── security.py              # Path traversal & subprocess isolation sandbox
│   ├── context_manager.py       # Token budgeting & sliding-window compaction
│   ├── model_capabilities.py    # Vision & model capability registry
│   ├── artifacts.py             # First-class artifact generation & storage
│   ├── citations.py             # Citations linking sources to messages
│   ├── backup.py                # Full workspace JSON export/import
│   ├── server.py                # FastAPI production server & SSE streaming
│   ├── test_suite.py            # Automated verification test suite
│   ├── uploads\                 # User uploaded files & images
│   └── artifacts\               # Generated code & document artifacts
│
├── static\
│   ├── css\
│   │   └── app.css              # Dark-mode styling, drawer, and tool cards
│   ├── js\
│   │   ├── state.js             # Central reactive state store
│   │   ├── api.js               # Typed API client & stream decoder
│   │   ├── markdown.js          # Markdown & code syntax renderer
│   │   ├── agent_ui.js          # Multi-step timeline & tool cards
│   │   ├── artifacts_ui.js      # Slide-out artifact drawer
│   │   └── app.js               # Master application coordinator
│   └── index.html               # Master SPA layout
│
├── start_web_ui.sh              # 1-Click macOS launcher
├── chat_cli.py                  # Terminal CLI interface
├── train_lora.py                # LoRA fine-tuning (Apple MPS + CUDA)
├── dataset_prep.py              # Training dataset validator
├── sample_dataset.jsonl         # Example chat fine-tuning data
├── Modelfile.template           # Ollama Modelfile template
├── Modelfile.m4pro-uncensored   # M4 Pro 32B uncensored Modelfile
├── MODEL_REFERENCE_AND_UPGRADES.md  # Reference guide on model identity
└── README.md                    # This master documentation
```

---

## 🍎 M4 Pro Model Recommendations

With 37 GB unified memory you can run significantly larger models than the original RTX 3060:

| Model | Pull Command | VRAM | Best For |
|---|---|---|---|
| **Qwen 2.5 32B** ⭐ | `ollama pull qwen2.5:32b` | ~20 GB | Best all-around: reasoning, coding, creative |
| **Qwen 2.5 Coder 32B** | `ollama pull qwen2.5-coder:32b` | ~20 GB | Elite code generation & debugging |
| **DeepSeek R1 32B** 🧠 | `ollama pull deepseek-r1:32b` | ~20 GB | Visible chain-of-thought reasoning |
| **Hermes 3** | `ollama pull hermes3` | ~5 GB | Uncensored, fast, expert tool use |
| **Dolphin 3 Llama3.1** | `ollama pull dolphin3.0-llama3.1:8b` | ~5 GB | Fully unrestricted, no guardrails |
| **Mistral Small 3.1 24B** 👁 | `ollama pull mistral-small3.1:24b` | ~14 GB | Vision + tools |
| **Llama 3.1 70B** | `ollama pull llama3.1:70b` | ~43 GB (tight) | Max capability (Q3_K_M: ~28 GB) |

Quick start with the recommended model:
```bash
ollama pull qwen2.5:32b
# Then create a custom uncensored persona:
ollama create studio-32b -f Modelfile.m4pro-uncensored
```

---

## 🧪 Automated Verification Suite

Run the full architectural test suite anytime:
```bash
python backend/test_suite.py
```
Outputs:
```text
[1] Security Sandbox Tests: [PASS]
[2] Context Management & Compaction Tests: [PASS]
[3] Model Capabilities & Vision Tests: [PASS]
[4] Artifact Generation & Extraction Tests: [PASS]
[5] Workspace Backup & Restore Tests: [PASS]
ALL TIER 2 ARCHITECTURE TESTS PASSED (100%)
```
