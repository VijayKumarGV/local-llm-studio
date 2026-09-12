"""
Multi-step agent orchestrator for Local LLM Studio.
Streams from Ollama over async httpx, uses native tool calling on /api/chat,
and re-enters the model loop with tool outputs until the model stops calling
tools or MAX_AGENT_STEPS is reached.
"""

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from backend import agent_tools, artifacts, citations, database, security
from backend.context_manager import prepare_compacted_context
from backend.model_capabilities import get_model_capabilities, validate_attachments_for_model
from backend.ollama_client import get_ollama_client

MAX_AGENT_STEPS = 8
TOOL_TIMEOUT_SECONDS = 30
MAX_THINK_ITERATIONS = 3

_REASONING_HINTS = re.compile(
    r"\b(why|prove|proof|analy[sz]e|compare|contrast|derive|explain|design|evaluate|trade[- ]?off|reason|justify|deduce|infer|debug|root ?cause)\b",
    re.IGNORECASE,
)
_CODE_HINTS = re.compile(
    r"\b(function|class|def |import |const |let |fn |struct |package |implement|refactor|method|algorithm|code|script|program|api|typescript|python|rust|golang|javascript)\b|```",
    re.IGNORECASE,
)


def _list_installed_models_sync() -> list[str]:
    """Synchronous best-effort installed-model list. Empty on any failure."""
    import urllib.request

    try:
        req = urllib.request.Request(f"{os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _has_image_attachment(attachments: list[dict[str, Any]] | None) -> bool:
    if not attachments:
        return False
    for a in attachments:
        m = (a.get("mime_type") or "").lower()
        fn = (a.get("filename") or "").lower()
        if m.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
            return True
    return False


def route_model(
    requested_model: str,
    user_message: str,
    project_id: str | None,
    settings: dict[str, str],
    installed: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Pick a model based on question shape + workspace + attachments + what's
    installed. Returns (chosen_model, reason). Falls back to requested_model on
    any doubt."""
    if not _setting_bool(settings, "auto_route_model", True):
        return requested_model, "auto-route disabled"

    installed = installed if installed is not None else _list_installed_models_sync()
    installed_set = set(installed)

    # Images always force a vision model — no text model can see them.
    if _has_image_attachment(attachments):
        req_caps = get_model_capabilities(requested_model)
        if req_caps.get("vision"):
            # Requested model already supports vision — keep it, don't let
            # downstream heuristics (like trivial-question → llama3.2:1b) strip
            # away the vision capability.
            return requested_model, "requested model supports vision — kept"
        for name in ("minicpm-v:latest", "minicpm-v", "llava:latest", "llava", "moondream:latest", "moondream"):
            if name in installed_set:
                return name, "image attachment — routed to vision model"

    # Per-workspace explicit override wins over heuristics
    if project_id:
        pref_key = f"project_{project_id}_default_model"
        if settings.get(pref_key) and settings[pref_key] in installed_set:
            return settings[pref_key], f"workspace default ({pref_key})"

    text_len = len(user_message.strip())
    reasoning_match = bool(_REASONING_HINTS.search(user_message))
    code_match = bool(_CODE_HINTS.search(user_message))

    # Ultra-short trivial questions → smallest model
    if text_len < 30 and not reasoning_match and not code_match:
        for name in ("llama3.2:1b", "llama3.2"):
            if name in installed_set:
                return name, f"trivial question ({text_len} chars)"

    # Reasoning-heavy question → reasoning model if available
    if reasoning_match:
        for name in ("deepseek-r1:14b", "deepseek-r1", "qwq:latest", "qwq"):
            if name in installed_set:
                return name, "reasoning keywords detected"

    # Code-heavy → coding specialist
    if code_match:
        for name in ("qwen2.5-coder:32b", "qwen2.5-coder"):
            if name in installed_set:
                return name, "code keywords detected"

    return requested_model, "default"


def _setting_bool(settings: dict[str, str], key: str, default: bool = True) -> bool:
    v = settings.get(key)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


def _tool_schemas() -> list[dict[str, Any]]:
    """Ollama-compatible function schemas built from the agent tool registry."""
    schemas = []
    for t in agent_tools.AVAILABLE_TOOLS:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )
    return schemas


class AgentOrchestrator:
    def __init__(self, user_settings: dict[str, str] | None = None):
        self._override_settings = user_settings

    @property
    def settings(self):
        return self._override_settings or database.get_settings()

    async def run_agent_loop(
        self,
        conversation_id: str,
        user_message: str,
        model_name: str = "qwen2.5:32b",
        enable_web_search: bool = False,
        enable_code_execution: bool = False,
        think_deeply: bool = False,
        attachments: list[dict[str, Any]] | None = None,
        cancellation_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[str, None]:
        execution_id = str(uuid.uuid4())
        conv = database.get_conversation(conversation_id)
        if not conv:
            yield f"event: error\ndata: {json.dumps({'error': 'Conversation not found'})}\n\n"
            return

        vision_warning = validate_attachments_for_model(model_name, attachments)
        if vision_warning:
            yield f"event: error\ndata: {json.dumps({'error': vision_warning})}\n\n"
            return

        user_msg = database.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            attachments=attachments or [],
        )

        # Auto-route to a better model for this specific question / attachments.
        settings_snapshot = self.settings
        routed_model, route_reason = route_model(
            requested_model=model_name,
            user_message=user_message,
            project_id=conv.get("project_id"),
            settings=settings_snapshot,
            attachments=attachments,
        )
        if routed_model != model_name:
            yield f"event: model_selected\ndata: {json.dumps({'requested': model_name, 'chosen': routed_model, 'reason': route_reason})}\n\n"
            model_name = routed_model

        yield f"event: execution_start\ndata: {json.dumps({'execution_id': execution_id, 'model': model_name})}\n\n"
        await asyncio.sleep(0)

        project_instructions = ""
        if conv.get("project_id"):
            proj = database.get_project(conv["project_id"])
            if proj:
                project_instructions = proj.get("system_instructions", "")

        attachment_context = ""
        rag_context = ""
        if attachments:
            for att in attachments:
                if att.get("id"):
                    f = database.get_file(att["id"])
                    if f and f.get("extracted_text"):
                        attachment_context += f"[File: {f['filename']}]\n{f['extracted_text']}\n\n"

        # RAG retrieval (opportunistic — silently no-ops if embeddings aren't set up)
        rag_hits_for_grounding: list[str] = []
        try:
            from backend import rag

            hits = await rag.retrieve(
                query=user_message,
                conversation_id=conversation_id,
                project_id=conv.get("project_id"),
                top_k=6,
            )
            rag_hits_for_grounding = [h.get("text", "") for h in (hits or [])]
            if hits:
                rag_context = "## Retrieved context from your files\n" + "\n\n".join(
                    f"[{h['filename']} · chunk {h['chunk_index']}]\n{h['text']}" for h in hits
                )
                for h in hits:
                    cite = citations.add_citation(
                        message_id=user_msg["id"],
                        conversation_id=conversation_id,
                        source_type="file",
                        title=f"{h['filename']} (chunk {h['chunk_index']})",
                        snippet=h["text"][:280],
                        url="",
                    )
                    yield f"event: citation\ndata: {json.dumps(cite)}\n\n"
                # Emit a debug payload with all retrieval scores so the UI can
                # show a "Retrieval details" panel.
                debug_hits = [
                    {
                        "filename": h.get("filename"),
                        "chunk_index": h.get("chunk_index"),
                        "fused_score": h.get("score"),
                        "rerank_score": h.get("rerank_score"),
                        "vector_score": h.get("vector_score"),
                        "vector_rank": h.get("vector_rank"),
                        "bm25_rank": h.get("bm25_rank"),
                        "snippet": (h.get("text") or "")[:400],
                    }
                    for h in hits
                ]
                yield f"event: retrieval_debug\ndata: {json.dumps({'query': user_message, 'hits': debug_hits})}\n\n"
        except Exception:
            pass

        # Long-term memory recall (silent no-op if unavailable)
        memory_context = ""
        try:
            from backend import long_term_memory

            memories = await long_term_memory.recall(
                query=user_message,
                project_id=conv.get("project_id"),
                top_k=5,
            )
            if memories:
                memory_context = "## What I remember about you\n" + "\n".join(
                    f"- ({m['category']}) {m['fact']}" for m in memories
                )
                yield f"event: memory_recalled\ndata: {json.dumps({'count': len(memories), 'facts': [m['fact'] for m in memories]})}\n\n"
        except Exception:
            pass

        system_instructions = self.settings.get("system_prompt", "")

        hardware_context = (
            "## Hardware Context\n"
            "You are running 100% locally and privately on an Apple M4 Pro with 37 GB unified memory. "
            "Zero cloud, zero telemetry, zero censorship, zero subscriptions. "
            "You can run large models (32B–70B parameters) directly on this machine.\n\n"
        )
        tool_hint = (
            "## Tools\n"
            "You have access to workspace tools including create_artifact, search_web, execute_python_code, "
            "read_file, list_files. Call them via the native function-calling interface — do NOT emit XML.\n"
            "Prefer create_artifact when producing any complete file (>10 lines, or intended to be saved/run).\n"
        )
        effective_system = hardware_context + system_instructions + "\n\n" + tool_hint
        if memory_context:
            effective_system = effective_system + "\n\n" + memory_context

        # Session scratchpad — model's own notes from previous turns.
        try:
            from backend import session_notes

            notes_block = session_notes.format_for_prompt(conversation_id)
            if notes_block:
                effective_system = effective_system + "\n\n" + notes_block
        except Exception:
            pass

        combined_user_context = user_message
        if rag_context:
            combined_user_context = f"{combined_user_context}\n\n{rag_context}"

        messages_payload = prepare_compacted_context(
            model_name=model_name,
            system_prompt=effective_system,
            project_instructions=project_instructions,
            conversation_history=conv.get("messages", []),
            current_user_message=combined_user_context,
            file_attachments_context=attachment_context,
        )

        # Sanitize legacy stringified tool_calls / attachments that came from DB history
        for m in messages_payload:
            if not isinstance(m.get("content"), str):
                m["content"] = "" if m.get("content") is None else str(m["content"])

        # Vision: attach base64 image data to the last user message when the
        # active model supports vision AND the user attached images.
        caps_now = get_model_capabilities(model_name)
        if caps_now.get("vision") and attachments:
            import base64 as _b64

            image_b64s = []
            for att in attachments:
                m = (att.get("mime_type") or "").lower()
                fn = (att.get("filename") or "").lower()
                is_img = m.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))
                if not is_img or not att.get("id"):
                    continue
                rec = database.get_file(att["id"])
                if not rec or not rec.get("filepath") or not os.path.exists(rec["filepath"]):
                    continue
                try:
                    with open(rec["filepath"], "rb") as fh:
                        image_b64s.append(_b64.b64encode(fh.read()).decode("ascii"))
                except Exception:
                    continue
            if image_b64s and messages_payload:
                # Attach to the last user message per Ollama's chat API convention.
                for m in reversed(messages_payload):
                    if m.get("role") == "user":
                        m["images"] = image_b64s
                        break
                yield f"event: vision_attached\ndata: {json.dumps({'images': len(image_b64s), 'model': model_name})}\n\n"

        caps = get_model_capabilities(model_name)
        model_supports_tools = caps.get("tools", False)

        tool_records: list[dict[str, Any]] = []
        created_citations: list[dict[str, Any]] = []
        created_artifacts: list[dict[str, Any]] = []
        final_content = ""
        total_tokens = 0
        final_tps = 0.0
        step = 0
        cumulative_completion = ""

        # Opt-in web search step before the model loop.
        if enable_web_search:
            step += 1
            yield f"event: plan_step\ndata: {json.dumps({'step': step, 'action': 'Searching Web for Context'})}\n\n"
            yield f"event: tool_start\ndata: {json.dumps({'tool': 'search_web', 'title': 'Searching Web', 'query': user_message})}\n\n"
            search_res = agent_tools.search_web(user_message)
            tool_records.append(
                {
                    "tool": "search_web",
                    "arguments": {"query": user_message},
                    "result": search_res,
                }
            )
            for r in search_res.get("results", [])[:3]:
                cite = citations.add_citation(
                    message_id=user_msg["id"],
                    conversation_id=conversation_id,
                    source_type="web",
                    title=r.get("title", "Web Source"),
                    snippet=r.get("snippet", ""),
                    url=r.get("url", ""),
                )
                created_citations.append(cite)
                yield f"event: citation\ndata: {json.dumps(cite)}\n\n"
            yield f"event: tool_end\ndata: {json.dumps({'tool': 'search_web', 'status': search_res.get('status'), 'result': search_res})}\n\n"

            snippets = "\n".join(
                f"- [{r.get('title')}]({r.get('url')}): {r.get('snippet')}" for r in search_res.get("results", [])
            )
            messages_payload.insert(
                1,
                {
                    "role": "system",
                    "content": f"[Observation from Web Search for '{user_message}']:\n{snippets}\n"
                    "Incorporate these verified facts into your response.",
                },
            )

        client = get_ollama_client()
        temperature = float(self.settings.get("default_temperature", 0.7))
        keep_alive = self.settings.get("keep_alive", "30m")
        available_tools = _tool_schemas() if model_supports_tools else None
        user_permissions = self.settings

        try:
            for _loop_iter in range(MAX_AGENT_STEPS):
                if cancellation_event and cancellation_event.is_set():
                    yield f"event: cancelled\ndata: {json.dumps({'message': 'Cancelled by user'})}\n\n"
                    return

                payload = {
                    "model": model_name,
                    "messages": messages_payload,
                    "stream": True,
                    "keep_alive": keep_alive,
                    "options": {"temperature": temperature},
                }
                if available_tools:
                    payload["tools"] = available_tools

                assistant_text = ""
                assistant_tool_calls: list[dict[str, Any]] = []
                got_done = False

                async with client.stream("POST", "/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        if cancellation_event and cancellation_event.is_set():
                            yield f"event: cancelled\ndata: {json.dumps({'message': 'Cancelled by user'})}\n\n"
                            return
                        try:
                            chunk = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue

                        msg = chunk.get("message", {}) or {}
                        delta = msg.get("content", "")
                        if delta:
                            assistant_text += delta
                            cumulative_completion += delta
                            total_tokens += 1
                            yield f"event: token\ndata: {json.dumps({'delta': delta})}\n\n"

                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                fn = tc.get("function", {}) or {}
                                name = fn.get("name")
                                args = fn.get("arguments") or {}
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except Exception:
                                        args = {}
                                if name:
                                    assistant_tool_calls.append({"name": name, "arguments": args})

                        if chunk.get("done"):
                            got_done = True
                            eval_count = chunk.get("eval_count", total_tokens)
                            eval_dur_ns = chunk.get("eval_duration", 1)
                            if eval_dur_ns > 0:
                                final_tps = round(eval_count / (eval_dur_ns / 1e9), 1)
                            break

                if not got_done:
                    # Connection dropped mid-stream; treat what we have as final.
                    break

                final_content = cumulative_completion

                if not assistant_tool_calls:
                    break  # model produced its final answer

                # Add the assistant turn to history so the model sees its own tool calls.
                messages_payload.append(
                    {
                        "role": "assistant",
                        "content": assistant_text,
                        "tool_calls": [
                            {"function": {"name": c["name"], "arguments": c["arguments"]}} for c in assistant_tool_calls
                        ],
                    }
                )

                for call in assistant_tool_calls:
                    if cancellation_event and cancellation_event.is_set():
                        yield f"event: cancelled\ndata: {json.dumps({'message': 'Cancelled by user'})}\n\n"
                        return

                    step += 1
                    tname = call["name"]
                    targs = call["arguments"]

                    perm = security.check_tool_permission(tname, user_permissions)
                    if perm == "disabled":
                        result = {"status": "denied", "error": f"Tool '{tname}' is disabled in settings."}
                        yield f"event: tool_denied\ndata: {json.dumps({'tool': tname, 'reason': result['error']})}\n\n"
                    elif perm == "require_approval":
                        if not enable_code_execution and tname == "execute_python_code":
                            result = {
                                "status": "denied",
                                "error": "Code execution disabled. Toggle 'Code Exec' in the composer to allow.",
                            }
                            yield f"event: tool_denied\ndata: {json.dumps({'tool': tname, 'reason': result['error']})}\n\n"
                        else:
                            result = await self._run_tool(tname, targs, conversation_id, conv, step)
                            async for evt in self._emit_tool_events(
                                tname,
                                targs,
                                result,
                                step,
                                user_msg["id"],
                                conversation_id,
                                created_citations,
                                created_artifacts,
                            ):
                                yield evt
                    else:
                        result = await self._run_tool(tname, targs, conversation_id, conv, step)
                        async for evt in self._emit_tool_events(
                            tname,
                            targs,
                            result,
                            step,
                            user_msg["id"],
                            conversation_id,
                            created_citations,
                            created_artifacts,
                        ):
                            yield evt

                    tool_records.append({"tool": tname, "arguments": targs, "result": result})
                    messages_payload.append(
                        {
                            "role": "tool",
                            "name": tname,
                            "content": json.dumps(result)[:6000],
                        }
                    )

            # --- THINK-DEEPLY: iterative critique + revise (up to MAX_THINK_ITERATIONS) ---
            if think_deeply and final_content:
                for iteration in range(1, MAX_THINK_ITERATIONS + 1):
                    yield f"event: thinking_phase\ndata: {json.dumps({'phase': 'critique', 'iteration': iteration, 'max_iterations': MAX_THINK_ITERATIONS, 'label': f'Reviewing draft (iter {iteration}/{MAX_THINK_ITERATIONS})'})}\n\n"

                    critique_prompt = [
                        {
                            "role": "system",
                            "content": (
                                "You are a strict senior reviewer. Given the user's question and a "
                                "draft response, list every real issue: factual errors, unsupported "
                                "claims, missing considerations, unclear steps, security or "
                                "correctness concerns, parts that fail to answer the actual question. "
                                "Be terse — bullet points, no praise. If the draft is genuinely "
                                "correct and complete, respond with EXACTLY the two words: NO ISSUES."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"USER QUESTION:\n{user_message}\n\nDRAFT RESPONSE:\n{final_content}",
                        },
                    ]
                    critique_text = ""
                    async with client.stream(
                        "POST",
                        "/api/chat",
                        json={
                            "model": model_name,
                            "messages": critique_prompt,
                            "stream": True,
                            "keep_alive": keep_alive,
                            "options": {"temperature": 0.2},
                        },
                    ) as cresp:
                        cresp.raise_for_status()
                        async for line in cresp.aiter_lines():
                            if not line:
                                continue
                            try:
                                c = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            d = (c.get("message") or {}).get("content", "")
                            if d:
                                critique_text += d
                            if c.get("done"):
                                break
                    yield f"event: critique\ndata: {json.dumps({'iteration': iteration, 'text': critique_text})}\n\n"

                    # If reviewer says clean, stop iterating.
                    lowered = critique_text.strip().lower()
                    if "no issues" in lowered[:80] or "no issue" in lowered[:80]:
                        yield f"event: thinking_phase\ndata: {json.dumps({'phase': 'done', 'iteration': iteration, 'label': f'Reviewer approved on iteration {iteration}'})}\n\n"
                        break

                    yield f"event: thinking_phase\ndata: {json.dumps({'phase': 'revise', 'iteration': iteration, 'label': f'Revising response (iter {iteration}/{MAX_THINK_ITERATIONS})'})}\n\n"
                    yield f"event: revision_start\ndata: {json.dumps({'iteration': iteration})}\n\n"

                    revise_prompt = [
                        {
                            "role": "system",
                            "content": (
                                "Produce the final response to the user's question. You have a draft "
                                "and a reviewer's critique of it. Fix every valid issue the reviewer "
                                "raised. Keep what the draft got right. Output ONLY the final response "
                                "— no preamble like 'Here is the revised version.'"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"USER QUESTION:\n{user_message}\n\n"
                                f"DRAFT:\n{final_content}\n\n"
                                f"REVIEWER CRITIQUE:\n{critique_text}"
                            ),
                        },
                    ]
                    revised = ""
                    async with client.stream(
                        "POST",
                        "/api/chat",
                        json={
                            "model": model_name,
                            "messages": revise_prompt,
                            "stream": True,
                            "keep_alive": keep_alive,
                            "options": {"temperature": temperature},
                        },
                    ) as rresp:
                        rresp.raise_for_status()
                        async for line in rresp.aiter_lines():
                            if not line:
                                continue
                            try:
                                r = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            d = (r.get("message") or {}).get("content", "")
                            if d:
                                revised += d
                                yield f"event: token\ndata: {json.dumps({'delta': d})}\n\n"
                            if r.get("done"):
                                break
                    if revised.strip():
                        final_content = revised
                    else:
                        break  # empty revision; stop iterating

            # --- GROUNDING CHECK: verify sentences against retrieved chunks ---
            if _setting_bool(settings_snapshot, "grounding_check", True) and rag_hits_for_grounding and final_content:
                try:
                    from backend import grounding

                    check = await grounding.check(final_content, rag_hits_for_grounding)
                    yield f"event: grounding_check\ndata: {json.dumps(check)}\n\n"
                except Exception as e:
                    yield f"event: grounding_check\ndata: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

            # Fallback: some non-tool-capable models still emit legacy XML artifacts.
            if not created_artifacts and final_content:
                legacy = artifacts.extract_and_save_artifacts(
                    text=final_content,
                    conversation_id=conversation_id,
                    project_id=conv.get("project_id"),
                )
                for art in legacy:
                    created_artifacts.append(art)
                    yield f"event: artifact_created\ndata: {json.dumps(art)}\n\n"

            asst_msg = database.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=final_content,
                token_count=total_tokens,
                eval_tps=final_tps,
                tool_calls=tool_records,
            )
            yield f"event: done\ndata: {json.dumps({'message_id': asst_msg['id'], 'content': final_content, 'token_count': total_tokens, 'eval_tps': final_tps, 'tool_calls': tool_records, 'citations': created_citations, 'artifacts': created_artifacts})}\n\n"

        except httpx.HTTPError as e:
            yield f"event: error\ndata: {json.dumps({'error': f'Ollama HTTP error: {e}'})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': f'Agent execution error: {e}'})}\n\n"

    async def _run_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        conversation_id: str,
        conv: dict[str, Any],
        step: int,
    ) -> dict[str, Any]:
        # Inject conversation_id into tools that need it but that the model
        # doesn't know about (scratchpad, artifacts).
        if tool_name in ("create_artifact", "save_note", "read_notes"):
            args = {**args, "conversation_id": conversation_id}
        if tool_name == "create_artifact":
            args["project_id"] = conv.get("project_id")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(agent_tools.dispatch_tool, tool_name, args),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return {"status": "error", "error": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _emit_tool_events(
        self,
        tname: str,
        targs: dict[str, Any],
        result: dict[str, Any],
        step: int,
        user_msg_id: str,
        conversation_id: str,
        created_citations: list[dict[str, Any]],
        created_artifacts: list[dict[str, Any]],
    ) -> AsyncGenerator[str, None]:
        title = tname
        if tname == "create_artifact":
            title = f"Creating Artifact: {targs.get('name', 'untitled')}"
        elif tname == "search_web":
            title = f"Searching Web: {targs.get('query', '')}"
        elif tname == "execute_python_code":
            title = "Executing Python Sandbox"

        yield f"event: plan_step\ndata: {json.dumps({'step': step, 'action': f'Invoking Tool: {tname}'})}\n\n"
        yield f"event: tool_start\ndata: {json.dumps({'tool': tname, 'title': title})}\n\n"

        if tname == "search_web":
            for r in (result.get("results") or [])[:3]:
                cite = citations.add_citation(
                    message_id=user_msg_id,
                    conversation_id=conversation_id,
                    source_type="web",
                    title=r.get("title", "Web Source"),
                    snippet=r.get("snippet", ""),
                    url=r.get("url", ""),
                )
                created_citations.append(cite)
                yield f"event: citation\ndata: {json.dumps(cite)}\n\n"

        if tname == "create_artifact" and result.get("status") == "success" and result.get("artifact_id"):
            saved = artifacts.get_artifact(result["artifact_id"])
            if saved:
                created_artifacts.append(saved)
                yield f"event: artifact_created\ndata: {json.dumps(saved)}\n\n"

        yield f"event: tool_end\ndata: {json.dumps({'tool': tname, 'status': result.get('status'), 'result': result})}\n\n"
