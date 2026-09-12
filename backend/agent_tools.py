"""
Agent tools engine for Local LLM Studio.
Provides real capabilities: live web search, Python execution sandbox, and workspace file reader.
"""

import sys
import os
import subprocess
import json
import urllib.request
import urllib.parse
import re
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==========================================
# TOOL 1: WEB SEARCH (DuckDuckGo Lite)
# ==========================================

def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web for up-to-date facts, documentation, or news."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results: List[Dict[str, Any]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, safesearch="moderate"):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        if not results:
            return {
                "query": query,
                "status": "success",
                "results": [{"title": "Web Search", "snippet": f"No results for '{query}'.", "url": ""}],
            }
        return {"query": query, "status": "success", "count": len(results), "results": results}
    except Exception as e:
        return {"query": query, "status": "error", "error": str(e)}


# ==========================================
# TOOL 2: PYTHON EXECUTION SANDBOX
# ==========================================

def execute_python_code(code: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """Execute Python code inside the macOS sandbox-exec profile (no network, tmpfs writes)."""
    from backend import security
    return security.run_sandboxed_python(code, timeout_seconds=timeout_seconds)


# ==========================================
# TOOL 3: WORKSPACE FILE READER
# ==========================================

def list_files(subdirectory: str = "") -> Dict[str, Any]:
    """List files in the local-llm-studio workspace."""
    target = os.path.normpath(os.path.join(WORKSPACE_DIR, subdirectory))
    if not target.startswith(WORKSPACE_DIR):
        return {"status": "error", "error": "Access denied: Path outside workspace."}

    try:
        entries = []
        for root, dirs, files in os.walk(target):
            # Exclude hidden or cache folders
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), WORKSPACE_DIR)
                entries.append(rel)
        return {"status": "success", "files": entries[:100]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def read_file(filepath: str, max_lines: int = 200) -> Dict[str, Any]:
    """Read contents of a workspace file."""
    target = os.path.normpath(os.path.join(WORKSPACE_DIR, filepath))
    if not target.startswith(WORKSPACE_DIR):
        return {"status": "error", "error": "Access denied: Path outside workspace."}

    if not os.path.exists(target):
        return {"status": "error", "error": f"File not found: {filepath}"}

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(max_lines)]
        return {
            "status": "success",
            "filepath": filepath,
            "content": "".join(lines)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ==========================================
# TOOL 4: ARTIFACT CREATION ENGINE
# ==========================================

def create_artifact(
    name: str,
    content: str,
    artifact_type: str = "code",
    conversation_id: str = None,
    project_id: str = None,
    language: str = ""
) -> Dict[str, Any]:
    """
    First-Class Tool: Creates and persists a workspace artifact via Artifact Service.
    Saves to filesystem, records in SQLite, and returns structured result.
    """
    from backend import artifacts
    art = artifacts.save_artifact(
        name=name,
        artifact_type=artifact_type,
        content=content,
        conversation_id=conversation_id,
        project_id=project_id,
        language=language
    )
    return {
        "status": "success",
        "artifact_id": art["id"],
        "name": art["name"],
        "type": art["type"],
        "language": art.get("language", ""),
        "size_bytes": art["size_bytes"],
        "message": f"Artifact '{name}' ({art['size_bytes']} bytes) successfully created and persisted to disk & database."
    }


# ==========================================
# TOOL REGISTRY & DISPATCHER
# ==========================================

def save_note(conversation_id: str, text: str, note_key: str = "") -> Dict[str, Any]:
    """Persist a short note to the current conversation's scratchpad. Notes
    are automatically injected into your context on future turns of THIS
    conversation. Use for plans, TODOs, constraints, open questions, or any
    working memory you want to keep across turns without cluttering messages."""
    from backend import session_notes
    return session_notes.save_note(conversation_id, text, note_key)


def read_notes(conversation_id: str, note_key: str = "") -> Dict[str, Any]:
    """Read your scratchpad. Optional note_key filters to a specific label."""
    from backend import session_notes
    key = note_key or None
    notes = session_notes.read_notes(conversation_id, key)
    return {"status": "success", "count": len(notes), "notes": notes}


def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch a specific URL and return the extracted main-content text.
    Different from search_web — that finds URLs, this reads one you already
    have. Use when the user pastes a link or a search result looks promising."""
    from backend import extractors
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return {"status": "error", "error": "url must start with http:// or https://"}
    try:
        text, title = extractors.fetch_url_as_text(url)
    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}
    return {
        "status": "success",
        "url": url,
        "title": title,
        "chars": len(text),
        "text": text[:8000],  # cap to keep tool result reasonable
    }


AVAILABLE_TOOLS = [
    {
        "name": "search_web",
        "description": "Search the web for up-to-date real-time facts, current events, software libraries, or news.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_url",
        "description": "Fetch a specific URL and return its main-content text. Use this when the user shares a link or when search returned a promising result you want to read in full.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full http:// or https:// URL to fetch."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "save_note",
        "description": "Save a short note to your conversation scratchpad. Notes persist across turns in THIS conversation and are auto-injected into your context on future turns. Use for: plans, TODOs, constraints, decisions, open questions, working memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The note content, max ~800 chars."},
                "note_key": {"type": "string", "description": "Optional short label (e.g. 'plan', 'todo', 'constraint')."}
            },
            "required": ["text"]
        }
    },
    {
        "name": "read_notes",
        "description": "Read notes you previously saved in this conversation's scratchpad. Notes are also auto-injected into context, so use this tool only when you want to check specifically or filter by note_key.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_key": {"type": "string", "description": "Optional filter — return only notes with this label."}
            }
        }
    },
    {
        "name": "execute_python_code",
        "description": "Run Python code locally in a sandbox. Use this to do exact math, calculations, data analysis, or run algorithms.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Executable Python code snippet."}
            },
            "required": ["code"]
        }
    },
    {
        "name": "read_file",
        "description": "Read contents of a file inside the local workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Relative path to file in workspace."}
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "list_files",
        "description": "List all files in the local workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "subdirectory": {"type": "string", "description": "Subdirectory to list (leave empty for root)."}
            }
        }
    },
    {
        "name": "create_artifact",
        "description": "Create a first-class file or document artifact (e.g. Python script, HTML page, markdown report, SVG, JSON). Call this tool whenever generating complete, inspectable files for the user to inspect, run, or download.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filename with extension (e.g. 'app.py', 'dashboard.html', 'report.md')"},
                "content": {"type": "string", "description": "Complete file content to be written."},
                "artifact_type": {"type": "string", "enum": ["code", "markdown", "html", "document", "svg", "data"], "description": "Type of artifact."},
                "language": {"type": "string", "description": "Programming or markup language (e.g. 'python', 'javascript', 'html')"}
            },
            "required": ["name", "content"]
        }
    }
]


def dispatch_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tool and return formatted result."""
    if tool_name == "search_web":
        return search_web(arguments.get("query", ""))
    elif tool_name == "fetch_url":
        return fetch_url(arguments.get("url", ""))
    elif tool_name == "execute_python_code":
        return execute_python_code(arguments.get("code", ""))
    elif tool_name == "read_file":
        return read_file(arguments.get("filepath", ""))
    elif tool_name == "list_files":
        return list_files(arguments.get("subdirectory", ""))
    elif tool_name == "save_note":
        conv = arguments.get("conversation_id", "")
        if not conv:
            return {"status": "error", "error": "conversation_id is set by orchestrator"}
        return save_note(conv, arguments.get("text", ""), arguments.get("note_key", ""))
    elif tool_name == "read_notes":
        conv = arguments.get("conversation_id", "")
        if not conv:
            return {"status": "error", "error": "conversation_id is set by orchestrator"}
        return read_notes(conv, arguments.get("note_key", ""))
    elif tool_name == "create_artifact":
        return create_artifact(
            name=arguments.get("name", "untitled.txt"),
            content=arguments.get("content", ""),
            artifact_type=arguments.get("artifact_type", "code"),
            conversation_id=arguments.get("conversation_id"),
            project_id=arguments.get("project_id"),
            language=arguments.get("language", "")
        )
    else:
        return {"status": "error", "error": f"Unknown tool: {tool_name}"}
