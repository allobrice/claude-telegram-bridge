#!/usr/bin/env python3
"""
Claude Code Hook: Notification
"""

import json
import os
import sys
import urllib.request

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")
BRIDGE_MODE = os.environ.get("CLAUDE_BRIDGE_MODE", "telegram").lower()

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

    message = hook_input.get("message", "")
    level = hook_input.get("level", "info")

    if not message:
        return

    # Register agent
    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
        }).encode()
        req = urllib.request.Request(
            f"{BRIDGE_URL}/register_agent",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        pass

    # Send notification
    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "message": message[:2000],
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
