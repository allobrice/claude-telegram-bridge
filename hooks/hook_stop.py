#!/usr/bin/env python3
"""
Claude Code Hook: Stop
"""

import json
import os
import sys
import urllib.request

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")

def main():
    raw = sys.stdin.read().strip()
    stop_reason = ""
    if raw:
        try:
            data = json.loads(raw)
            stop_reason = data.get("stop_reason", "")
        except json.JSONDecodeError:
            pass

    message = f"🏁 Agent terminé"
    if stop_reason:
        message += f"\nRaison: {stop_reason}"

    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "message": message,
            "level": "task_complete",
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

    try:
        payload = json.dumps({"agent_id": AGENT_ID}).encode()
        req = urllib.request.Request(
            f"{BRIDGE_URL}/unregister_agent",
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
