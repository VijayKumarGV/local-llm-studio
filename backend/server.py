"""
Production FastAPI Server for Local LLM Studio.
Coordinates the Agent Orchestrator, SQLite persistence, Artifact engine,
model capability detection, and workspace backup/restore.
"""

import asyncio
import hmac
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend import (
    artifacts,
    backup,
    database,
    extractors,
    feedback,
    long_term_memory,
    model_capabilities,
    rag,
    session_notes,
)
from backend.agent_orchestrator import AgentOrchestrator
from backend.auth import COOKIE_NAME, auth_middleware, load_or_create_token
from backend.middleware import RequestIdFilter, request_context_middleware
from backend.migrations import apply_migrations
from backend.ollama_client import close_ollama_client, get_ollama_client
from backend.rate_limit import LIMIT_CHAT_STREAM, LIMIT_COMPARE, LIMIT_SANDBOX, LIMIT_UPLOAD, limiter
from backend.security_headers import security_headers_middleware

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Attach request-id filter to the ROOT logger so every child logger inherits.
logging.getLogger().addFilter(RequestIdFilter())
log = logging.getLogger("studio")

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    rag.ensure_schema()
    long_term_memory.ensure_schema()
    session_notes.ensure_schema()
    feedback.ensure_schema()
    applied = apply_migrations(database.DB_PATH)
    if applied:
        log.info("applied %d migration(s)", applied)
    yield
    await close_ollama_client()


app = FastAPI(title="Local LLM Studio API — M4 Pro Edition", version="0.3.0", lifespan=lifespan)

# Rate limiter — 120 req/min by default, tighter on hot endpoints below.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Middleware registration is INSIDE-OUT — the last one registered becomes
# the OUTERMOST wrapper. We want:
#   security_headers → auth → request_context → endpoint
# So security headers wrap every response (including 401s from auth), and
# request IDs are available to endpoint code.
app.middleware("http")(request_context_middleware)  # innermost — sets request_id_var
app.middleware("http")(auth_middleware)  # middle — 401s bubble up through security
app.middleware("http")(security_headers_middleware)  # outermost — decorates every response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

orchestrator = AgentOrchestrator()


# ==========================================
# MODELS & SCHEMAS
# ==========================================


class ProjectCreate(BaseModel):
    name: str
    description: str | None = ""
    system_instructions: str | None = ""
    icon: str | None = "📁"
    color: str | None = "#38bdf8"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_instructions: str | None = None
    icon: str | None = None
    color: str | None = None
    pinned: int | None = None


class ConversationCreate(BaseModel):
    title: str | None = "New Conversation"
    project_id: str | None = None
    model: str | None = "qwen2.5:32b"
    system_prompt: str | None = ""
    temperature: float | None = 0.7


class ConversationUpdate(BaseModel):
    title: str | None = None
    project_id: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    pinned: int | None = None
    archived: int | None = None


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    model: str | None = "qwen2.5:32b"
    system_prompt: str | None = None
    temperature: float | None = 0.7
    enable_web_search: bool | None = False
    enable_code_execution: bool | None = False
    think_deeply: bool | None = False
    attachments: list[dict[str, Any]] | None = None


# ==========================================
# SYSTEM & OLLAMA ENDPOINTS
# ==========================================


@app.post("/api/memory/extract")
async def memory_extract(req: Request):
    body = await req.json()
    conv_id = body.get("conversation_id")
    if not conv_id:
        raise HTTPException(status_code=400, detail="conversation_id required")
    result = await long_term_memory.extract_from_conversation(
        conv_id,
        replace_existing=bool(body.get("replace_existing", False)),
    )
    return result


@app.get("/api/memory")
def memory_list(project_id: str | None = None, limit: int = 100):
    return {"status": "success", "memories": long_term_memory.list_memories(project_id, limit)}


@app.delete("/api/memory/{memory_id}")
def memory_delete(memory_id: str):
    long_term_memory.delete_memory(memory_id)
    return {"status": "success"}


@app.get("/api/rag/query")
async def rag_query(q: str, project_id: str | None = None, conversation_id: str | None = None, top_k: int = 6):
    """Debug endpoint: run retrieval and return hits + hybrid scores. Lets you
    eyeball retrieval quality without opening a chat."""
    if not q.strip():
        return {"status": "error", "error": "empty query"}
    hits = await rag.retrieve(
        query=q,
        project_id=project_id,
        conversation_id=conversation_id,
        top_k=top_k,
    )
    for h in hits:
        h["text"] = (h.get("text") or "")[:400]  # truncate for readability
    return {"status": "success", "query": q, "hits": hits, "count": len(hits)}


@app.get("/api/health")
async def health():
    """Liveness + readiness. Reports ollama connectivity, model count, db path."""
    ollama_up = False
    model_count = 0
    embed_ready = False
    try:
        client = get_ollama_client()
        resp = await client.get("/api/tags", timeout=2.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        ollama_up = True
        model_count = len(models)
        embed_ready = any("nomic-embed" in m.get("name", "") for m in models)
    except Exception as e:
        log.warning("health: ollama unreachable: %s", e)
    return {
        "status": "ok" if ollama_up else "degraded",
        "ollama": {"up": ollama_up, "models": model_count},
        "rag": {"embed_model_pulled": embed_ready},
        "db_path": database.DB_PATH,
    }


@app.get("/api/models")
async def get_models():
    """List available models from Ollama with enhanced capability metadata."""
    try:
        client = get_ollama_client()
        resp = await client.get("/api/tags", timeout=4.0)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models", [])
        for m in models:
            m["capabilities"] = model_capabilities.get_model_capabilities(m.get("name", ""))
        return {"status": "success", "models": models}
    except Exception as e:
        return {"status": "error", "error": f"Failed to connect to Ollama: {e}", "models": []}


@app.get("/api/models/capabilities")
def get_model_caps(name: str):
    caps = model_capabilities.get_model_capabilities(name)
    return {"status": "success", "capabilities": caps}


# ==========================================
# PROJECTS ENDPOINTS
# ==========================================


@app.get("/api/projects")
def list_projects():
    return {"status": "success", "projects": database.list_projects()}


@app.post("/api/projects")
def create_project(data: ProjectCreate):
    proj = database.create_project(
        name=data.name,
        description=data.description or "",
        system_instructions=data.system_instructions or "",
        icon=data.icon or "📁",
        color=data.color or "#38bdf8",
    )
    return {"status": "success", "project": proj}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "success", "project": proj}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, data: ProjectUpdate):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    proj = database.update_project(project_id, **update_data)
    return {"status": "success", "project": proj}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    database.delete_project(project_id)
    return {"status": "success"}


# ==========================================
# CONVERSATIONS ENDPOINTS
# ==========================================


@app.get("/api/conversations")
def list_conversations(project_id: str | None = None, include_archived: bool = False):
    convs = database.list_conversations(project_id=project_id, include_archived=include_archived)
    return {"status": "success", "conversations": convs}


@app.post("/api/conversations")
def create_conversation(data: ConversationCreate):
    conv = database.create_conversation(
        title=data.title or "New Conversation",
        project_id=data.project_id,
        model=data.model or "qwen2.5:32b",
        system_prompt=data.system_prompt or "",
        temperature=data.temperature or 0.7,
    )
    return {"status": "success", "conversation": conv}


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str):
    conv = database.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "conversation": conv}


@app.patch("/api/conversations/{conv_id}")
def update_conversation(conv_id: str, data: ConversationUpdate):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    conv = database.update_conversation(conv_id, **update_data)
    return {"status": "success", "conversation": conv}


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    database.delete_conversation(conv_id)
    return {"status": "success"}


@app.post("/api/conversations/{conv_id}/duplicate")
def duplicate_conversation(conv_id: str):
    new_conv = database.duplicate_conversation(conv_id)
    if not new_conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "conversation": new_conv}


@app.post("/api/conversations/{conv_id}/branch")
async def branch_conversation_endpoint(conv_id: str, req: Request):
    body = await req.json()
    message_id = body.get("message_id")
    if not message_id:
        raise HTTPException(status_code=400, detail="message_id required")
    new_conv = database.branch_conversation(conv_id, message_id)
    if not new_conv:
        raise HTTPException(status_code=404, detail="Failed to branch conversation")
    return {"status": "success", "conversation": new_conv}


@app.delete("/api/messages/{message_id}")
def delete_message(message_id: str):
    database.delete_message(message_id)
    return {"status": "success"}


# ==========================================
# ARTIFACTS API
# ==========================================


@app.get("/api/artifacts")
def get_artifacts(conversation_id: str | None = None, project_id: str | None = None):
    items = artifacts.list_artifacts(conversation_id, project_id)
    return {"status": "success", "artifacts": items}


@app.get("/api/artifacts/{artifact_id}")
def get_single_artifact(artifact_id: str):
    art = artifacts.get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"status": "success", "artifact": art}


@app.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    art = artifacts.get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return Response(
        content=art["content"],
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={art['name']}"},
    )


# ==========================================
# FILE UPLOAD & MANAGEMENT
# ==========================================


@app.post("/api/files/upload")
@limiter.limit(LIMIT_UPLOAD)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    conversation_id: str | None = Form(None),
    project_id: str | None = Form(None),
):
    try:
        fid = str(uuid.uuid4())
        save_filename = f"{fid}_{file.filename}"
        save_path = os.path.join(UPLOAD_DIR, save_filename)

        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        size_bytes = os.path.getsize(save_path)
        mime_type = file.content_type or "application/octet-stream"

        # Extract full text (PDF via pypdf, text/code via UTF-8 read).
        full_text, kind = extractors.extract_text_from_file(save_path, mime_type)
        extracted_preview = full_text[:4000]

        record = database.add_file(
            filename=file.filename or f"{fid}.bin",
            filepath=save_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            conversation_id=conversation_id,
            project_id=project_id,
            extracted_text=extracted_preview,
        )

        rag_result: dict[str, Any] = {"status": "skipped", "reason": "no extractable text"}
        if full_text.strip():
            try:
                rag_result = await rag.ingest_file(record["id"], text=full_text)
            except Exception as e:
                rag_result = {"status": "error", "error": str(e)}

        return {
            "status": "success",
            "file": record,
            "kind": kind,
            "extracted_preview": extracted_preview[:200],
            "extracted_chars": len(full_text),
            "rag": rag_result,
        }
    except Exception as e:
        log.exception("upload failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/feedback")
async def feedback_record(req: Request):
    """Record 👍 (+1) / 👎 (-1) / unrate (0) on an assistant message."""
    body = await req.json()
    mid = body.get("message_id")
    rating = int(body.get("rating", 0))
    if not mid:
        raise HTTPException(status_code=400, detail="message_id required")
    return feedback.record(mid, rating, body.get("note", ""))


@app.get("/api/feedback")
def feedback_get(message_id: str | None = None, conversation_id: str | None = None):
    if message_id:
        return {"status": "success", "feedback": feedback.get_for_message(message_id)}
    return {"status": "success", "summary": feedback.summary(conversation_id)}


@app.post("/api/chat/compare")
@limiter.limit(LIMIT_COMPARE)
async def chat_compare(request: Request):
    req = request
    """Run the same prompt against two models in parallel. Non-streaming,
    returns both answers together for side-by-side review. No history,
    no tools, no RAG — this is a pure A/B on model output."""
    body = await req.json()
    prompt = (body.get("message") or "").strip()
    model_a = body.get("model_a") or "qwen2.5:32b"
    model_b = body.get("model_b") or "dolphin3:latest"
    if not prompt:
        raise HTTPException(status_code=400, detail="message required")
    system_prompt = body.get("system_prompt", "")
    temperature = float(body.get("temperature", 0.7))

    client = get_ollama_client()

    async def _one(model_name: str) -> dict[str, Any]:
        payload = {
            "model": model_name,
            "stream": False,
            "keep_alive": "30m",
            "messages": (
                ([{"role": "system", "content": system_prompt}] if system_prompt else [])
                + [{"role": "user", "content": prompt}]
            ),
            "options": {"temperature": temperature},
        }
        try:
            resp = await client.post("/api/chat", json=payload, timeout=300.0)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message") or {}
            eval_dur_ns = data.get("eval_duration", 1)
            eval_count = data.get("eval_count", 0)
            tps = round(eval_count / (eval_dur_ns / 1e9), 1) if eval_dur_ns > 0 else 0.0
            return {
                "model": model_name,
                "content": msg.get("content", ""),
                "tokens": eval_count,
                "tps": tps,
                "status": "success",
            }
        except Exception as e:
            return {"model": model_name, "content": "", "status": "error", "error": str(e)}

    a, b = await asyncio.gather(_one(model_a), _one(model_b))
    return {"status": "success", "a": a, "b": b}


@app.post("/api/sandbox/run")
@limiter.limit(LIMIT_SANDBOX)
async def sandbox_run(request: Request):
    req = request
    """Run a Python snippet in the macOS sandbox-exec profile. Returns stdout,
    stderr, exit code. Used by the frontend Run button on code blocks."""
    body = await req.json()
    code = body.get("code", "")
    if not code.strip():
        raise HTTPException(status_code=400, detail="code required")
    timeout_s = int(body.get("timeout", 10))
    from backend import security

    result = security.run_sandboxed_python(code, timeout_seconds=timeout_s)
    return result


@app.post("/api/files/from-url")
async def upload_from_url(req: Request):
    """Fetch a public URL, extract main content, save + ingest into RAG."""
    body = await req.json()
    url = (body.get("url") or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Valid http(s) URL required")
    conversation_id = body.get("conversation_id")
    project_id = body.get("project_id")

    try:
        text, title = extractors.fetch_url_as_text(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e}") from e
    if not text or len(text) < 100:
        raise HTTPException(status_code=422, detail="No extractable main-content found at URL")

    # Save the extracted text as a .md file so it lands in normal upload flow
    fid = str(uuid.uuid4())
    safe_title = "".join(c if c.isalnum() or c in "-_. " else "_" for c in title)[:80]
    filename = f"{safe_title}.md" if safe_title else f"webpage_{fid[:8]}.md"
    save_path = os.path.join(UPLOAD_DIR, f"{fid}_{filename}")
    header = f"# {title}\n\nSource: {url}\n\n"
    with open(save_path, "w", encoding="utf-8") as fh:
        fh.write(header + text)

    record = database.add_file(
        filename=filename,
        filepath=save_path,
        mime_type="text/markdown",
        size_bytes=os.path.getsize(save_path),
        conversation_id=conversation_id,
        project_id=project_id,
        extracted_text=(header + text)[:4000],
    )
    rag_result: dict[str, Any] = {"status": "skipped"}
    try:
        rag_result = await rag.ingest_file(record["id"], text=header + text)
    except Exception as e:
        rag_result = {"status": "error", "error": str(e)}

    return {
        "status": "success",
        "file": record,
        "url": url,
        "title": title,
        "extracted_chars": len(text),
        "rag": rag_result,
    }


@app.get("/api/files/{file_id}")
def get_file_content(file_id: str):
    record = database.get_file(file_id)
    if not record or not os.path.exists(record["filepath"]):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(record["filepath"], filename=record["filename"], media_type=record["mime_type"])


@app.get("/api/projects/{project_id}/files")
def get_project_files(project_id: str):
    files = database.list_files_by_project(project_id)
    return {"status": "success", "files": files}


@app.delete("/api/files/{file_id}")
def delete_file_endpoint(file_id: str):
    import contextlib

    record = database.get_file(file_id)
    if record and os.path.exists(record["filepath"]):
        with contextlib.suppress(OSError):
            os.remove(record["filepath"])
    database.delete_file(file_id)
    return {"status": "success"}


# ==========================================
# WORKSPACE BACKUP & RESTORE
# ==========================================


@app.get("/api/workspace/export")
def export_workspace_endpoint():
    data = backup.export_full_workspace()
    return JSONResponse(content=data)


@app.post("/api/workspace/import")
async def import_workspace_endpoint(req: Request):
    data = await req.json()
    result = backup.import_workspace(data)
    return {"status": "success", "imported": result}


# ==========================================
# GLOBAL SEARCH & SETTINGS
# ==========================================


@app.get("/api/search")
def search(q: str):
    results = database.global_search(q)
    return {"status": "success", "results": results}


@app.get("/api/settings")
def get_settings():
    return {"status": "success", "settings": database.get_settings()}


@app.post("/api/settings")
async def save_settings(req: Request):
    data = await req.json()
    for k, v in data.items():
        database.save_setting(k, str(v))
    return {"status": "success", "settings": database.get_settings()}


# ==========================================
# MULTI-STEP AGENT STREAMING
# ==========================================


@app.post("/api/chat/stream")
@limiter.limit(LIMIT_CHAT_STREAM)
async def stream_chat(request: Request, req: ChatRequest):
    """
    Dedicated Multi-Step Agent Execution Endpoint.
    Delegates to AgentOrchestrator for autonomous tool loops, citations, and artifacts.
    """
    return StreamingResponse(
        orchestrator.run_agent_loop(
            conversation_id=req.conversation_id,
            user_message=req.message,
            model_name=req.model or "qwen2.5:32b",
            enable_web_search=req.enable_web_search or False,
            enable_code_execution=req.enable_code_execution or False,
            think_deeply=req.think_deeply or False,
            attachments=req.attachments or [],
        ),
        media_type="text/event-stream",
    )


# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _asset_hash() -> str:
    """Short hash of the primary JS + CSS files. Recomputed on every GET /
    so browsers auto-invalidate when we ship changes."""
    import hashlib

    h = hashlib.sha256()
    for rel in ("js/app.js", "js/markdown.js", "js/api.js", "js/state.js", "css/app.css"):
        p = os.path.join(STATIC_DIR, rel)
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except FileNotFoundError:
            continue
    return h.hexdigest()[:12]


@app.get("/")
def serve_index() -> Response:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace("__ASSET_HASH__", _asset_hash())
    return Response(content=html, media_type="text/html")


@app.get("/auth")
def bootstrap_auth(token: str) -> Response:
    """One-shot browser bootstrap: sets the session cookie and redirects to /.
    Any mismatch → 401 with a hint."""
    expected = load_or_create_token()
    if not hmac.compare_digest(token, expected):
        return JSONResponse({"error": "invalid token"}, status_code=401)
    resp = Response(status_code=302, headers={"Location": "/"})
    # httponly=False so the SPA's fetch() can still read it if needed for
    # explicit Authorization header (not required — cookie alone works).
    resp.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 365,  # 1 year
        secure=False,  # local http; flip to True behind TLS
    )
    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.server:app", host="127.0.0.1", port=8080, reload=False)
