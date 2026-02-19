#!/usr/bin/env python3
"""
Claude Code Hook: PostToolUse
"""

import json
import os
import sys
import urllib.request

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")
BRIDGE_MODE = os.environ.get("CLAUDE_BRIDGE_MODE", "telegram").lower()

NOTIFY_TOOLS = {"bash", "write", "edit", "execute"}
NOTIFY_ON_ERROR = True

def main():
    if BRIDGE_MODE == "local":
        return

    raw = sys.stdin.read().strip()
    if not raw:
        return

    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        return

    tool_name = hook_input.get("tool_name", "unknown")
    tool_output = hook_input.get("tool_output", "")
    was_error = hook_input.get("was_error", False)

    should_notify = tool_name in NOTIFY_TOOLS or (NOTIFY_ON_ERROR and was_error)
    if not should_notify:
        return

    if was_error:
        level = "error"
        status = "❌ Erreur"
    else:
        level = "success"
        status = "✅ OK"

    output_preview = str(tool_output)[:300]
    if len(str(tool_output)) > 300:
        output_preview += "..."

    message = f"Outil: {tool_name} → {status}\n\n{output_preview}"

    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "message": message,
            "level": level,
        }).encode()

        req = urllib.request.Request(
            f"{BRIDGE_URL}/notify",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass

if __name__ == "__main__":
    main()
