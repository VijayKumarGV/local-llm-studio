import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

import pytest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import database

BASE_URL = "http://127.0.0.1:8080"


def _server_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason="requires studio server running on :8080")


def request_json(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_audit():
    print("==================================================")
    print("STARTING FULL END-TO-END AUDIT SUITE")
    print("==================================================")

    # ----------------------------------------------------
    # AUDIT 1: PROJECTS AND WORKSPACES
    # ----------------------------------------------------
    print("\n[AUDIT 1] Testing Project / Workspace Operations...")
    proj_res = request_json(
        "/api/projects",
        method="POST",
        data={
            "name": "Audit Workspace Alpha",
            "description": "Workspace for audit testing",
            "system_instructions": "Always provide concise, verified answers with references.",
        },
    )
    assert proj_res["status"] == "success", "Failed to create project"
    proj_id = proj_res["project"]["id"]
    print(f"  [OK] Project created with ID: {proj_id}")

    # Update project instructions
    up_res = request_json(
        f"/api/projects/{proj_id}",
        method="PATCH",
        data={"system_instructions": "Updated custom instructions for project."},
    )
    assert up_res["status"] == "success"
    assert up_res["project"]["system_instructions"] == "Updated custom instructions for project."
    print("  [OK] Project instructions updated successfully")

    # Upload file attached to project
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    file_content = "def audit_math(a, b):\n    return a * b + 42\n"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="project_id"\r\n\r\n'
        f"{proj_id}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="audit_math.py"\r\n'
        f"Content-Type: text/x-python\r\n\r\n"
        f"{file_content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        f"{BASE_URL}/api/files/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        upload_res = json.loads(r.read().decode("utf-8"))
    assert upload_res["status"] == "success"
    file_id = upload_res["file"]["id"]
    print(f"  [OK] Uploaded project file ID: {file_id}")

    # Check project files listing
    pfiles = request_json(f"/api/projects/{proj_id}/files")
    assert len(pfiles["files"]) >= 1
    assert pfiles["files"][0]["filename"] == "audit_math.py"
    print(f"  [OK] Project files listed: {len(pfiles['files'])} file(s) found")

    # ----------------------------------------------------
    # AUDIT 2: CONVERSATION LIFECYCLE AND SIDEBAR ACTIONS
    # ----------------------------------------------------
    print("\n[AUDIT 2] Testing Sidebar & Conversation Lifecycle...")
    c1_res = request_json(
        "/api/conversations",
        method="POST",
        data={"title": "Initial Audit Chat", "project_id": None, "model": "qwen2.5:32b"},
    )
    c1_id = c1_res["conversation"]["id"]
    print(f"  [OK] Conversation created: {c1_id}")

    # Pin conversation
    request_json(f"/api/conversations/{c1_id}", method="PATCH", data={"pinned": 1})
    c1_get = request_json(f"/api/conversations/{c1_id}")
    assert c1_get["conversation"]["pinned"] == 1
    print("  [OK] Conversation pinned successfully")

    # Rename conversation
    request_json(f"/api/conversations/{c1_id}", method="PATCH", data={"title": "Renamed Audit Chat"})
    c1_get = request_json(f"/api/conversations/{c1_id}")
    assert c1_get["conversation"]["title"] == "Renamed Audit Chat"
    print("  [OK] Conversation renamed successfully")

    # Move conversation into Project Workspace
    request_json(f"/api/conversations/{c1_id}", method="PATCH", data={"project_id": proj_id})
    c1_get = request_json(f"/api/conversations/{c1_id}")
    assert c1_get["conversation"]["project_id"] == proj_id
    print("  [OK] Conversation moved into Project Workspace")

    # Filter conversations by Project
    proj_convs = request_json(f"/api/conversations?project_id={proj_id}")
    assert any(c["id"] == c1_id for c in proj_convs["conversations"])
    print("  [OK] Filter by project accurately returns associated conversation")

    # Archive conversation
    request_json(f"/api/conversations/{c1_id}", method="PATCH", data={"archived": 1})
    unarchived_list = request_json("/api/conversations")
    assert not any(c["id"] == c1_id for c in unarchived_list["conversations"]), (
        "Archived conversation should not appear in unarchived list"
    )
    archived_list = request_json("/api/conversations?include_archived=true")
    assert any(c["id"] == c1_id for c in archived_list["conversations"]), (
        "Archived conversation should appear when include_archived=true"
    )
    print("  [OK] Archiving properly filters conversation from active list and persists in archived list")

    # Unarchive conversation
    request_json(f"/api/conversations/{c1_id}", method="PATCH", data={"archived": 0})
    unarchived_list2 = request_json("/api/conversations")
    assert any(c["id"] == c1_id for c in unarchived_list2["conversations"])
    print("  [OK] Unarchiving restores conversation to active sidebar list")

    # ----------------------------------------------------
    # AUDIT 3: MESSAGES, BRANCHING AND HISTORY FORKING
    # ----------------------------------------------------
    print("\n[AUDIT 3] Testing Messages, History Forking & Branching...")
    # Add turn 1: User
    database.add_message(c1_id, "user", "What is the capital of France?")
    # Add turn 1: Assistant
    database.add_message(c1_id, "assistant", "The capital of France is Paris.")
    # Add turn 2: User (the branch point)
    m2_user = database.add_message(c1_id, "user", "What is its primary river?")
    m2_user_id = m2_user["id"]
    # Add turn 2: Assistant
    database.add_message(c1_id, "assistant", "The primary river flowing through Paris is the Seine.")
    # Add turn 3: User
    database.add_message(c1_id, "user", "What is the famous museum near it?")
    database.add_message(c1_id, "assistant", "The Louvre museum is located on the right bank of the Seine.")

    full_conv = request_json(f"/api/conversations/{c1_id}")
    assert len(full_conv["conversation"]["messages"]) == 6
    print("  [OK] Seeded 6 messages across 3 turns in base conversation")

    # Branch from turn 2 user message
    branch_res = request_json(f"/api/conversations/{c1_id}/branch", method="POST", data={"message_id": m2_user_id})
    assert branch_res["status"] == "success"
    branch_id = branch_res["conversation"]["id"]
    branch_conv = request_json(f"/api/conversations/{branch_id}")
    branch_msgs = branch_conv["conversation"]["messages"]

    # The branched conversation should have exactly 3 messages (turn 1 user, turn 1 ai, turn 2 user)
    assert len(branch_msgs) == 3, f"Expected 3 messages in branch, got {len(branch_msgs)}"
    assert branch_msgs[-1]["id"] != m2_user_id  # new copies with new IDs
    assert branch_msgs[-1]["content"] == "What is its primary river?"
    print(
        f"  [OK] Forked/Branched conversation successfully created (ID: {branch_id}) containing exact history up to target message turn"
    )

    # ----------------------------------------------------
    # AUDIT 4: GLOBAL SEARCH
    # ----------------------------------------------------
    print("\n[AUDIT 4] Testing Global Search (Ctrl+K)...")
    s_res = request_json("/api/search?q=Seine")
    assert s_res["status"] == "success"
    assert len(s_res["results"]["messages"]) >= 1
    assert "Seine" in s_res["results"]["messages"][0]["content"]
    print(f"  [OK] Global search found target snippet: '{s_res['results']['messages'][0]['content'][:40]}...'")

    # ----------------------------------------------------
    # AUDIT 5: BACKUP AND RESTORE
    # ----------------------------------------------------
    print("\n[AUDIT 5] Testing Full Workspace Export & Backup...")
    export_res = request_json("/api/workspace/export")
    assert "projects" in export_res and "conversations" in export_res and "messages" in export_res
    print(
        f"  [OK] Exported workspace: {len(export_res['projects'])} project(s), {len(export_res['conversations'])} conversation(s), {len(export_res['messages'])} message(s)"
    )

    # ----------------------------------------------------
    # AUDIT 6: CLEANUP AUDIT ENTITIES
    # ----------------------------------------------------
    print("\n[AUDIT 6] Cleaning up test artifacts...")
    request_json(f"/api/files/{file_id}", method="DELETE")
    request_json(f"/api/conversations/{c1_id}", method="DELETE")
    request_json(f"/api/conversations/{branch_id}", method="DELETE")
    request_json(f"/api/projects/{proj_id}", method="DELETE")
    print("  [OK] Cleanup complete")

    print("\n==================================================")
    print("ALL 6 AUDIT SUITES PASSED (100% SUCCESS)")
    print("==================================================")


if __name__ == "__main__":
    test_audit()
