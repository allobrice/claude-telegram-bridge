#!/usr/bin/env python3
"""
Claude Code Hook: PostToolUse
==============================
Ce hook notifie Telegram APRÈS l'exécution d'un outil.
Utile pour suivre l'activité de l'agent à distance.

Installation dans ~/.claude/settings.json:
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "python3 /chemin/vers/hook_post_tool_use.py"
      }
    ]
  }
}
"""

import json
import os
import sys
import urllib.request
import urllib.error

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")

# Only notify for these tools (to avoid spam)
NOTIFY_TOOLS = {
    "bash",
    "write",
    "edit",
    "execute",
}

# Notify on errors for any tool
NOTIFY_ON_ERROR = True


def main():
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

    # Decide whether to notify
    should_notify = tool_name in NOTIFY_TOOLS or (NOTIFY_ON_ERROR and was_error)
    if not should_notify:
        return

    # Build message
    if was_error:
        level = "error"
        status = "❌ Erreur"
    else:
        level = "success"
        status = "✅ OK"

    # Truncate output
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception:
        pass  # Non-blocking, don't interrupt the agent


if __name__ == "__main__":
    main()
