#!/usr/bin/env python3
"""
Claude Code Hook: PreToolUse
=============================
Ce hook intercepte AVANT l'exécution d'un outil par Claude Code.
Il envoie une demande d'approbation au bridge Telegram et attend la réponse.

Installation:
  Copier dans ~/.claude/hooks/ et configurer dans ~/.claude/settings.json

Usage dans settings.json:
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python3 /chemin/vers/hook_pre_tool_use.py"
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

# ─── Configuration ────────────────────────────────────────────────────────────

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")

# Tools that ALWAYS require approval (never auto-approved)
CRITICAL_TOOLS = {
    "bash",
    "write",
    "edit",
    "execute",  # Add any dangerous tools
}

# Tools that NEVER need approval (always auto-approved)
SAFE_TOOLS = {
    "read",
    "list_files",
    "search",
    "grep",
    "glob",
    "view",
}

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Read hook input from stdin
    raw = sys.stdin.read().strip()
    if not raw:
        # No input, allow by default
        output({"decision": "approve"})
        return

    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        output({"decision": "approve"})
        return

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = json.dumps(hook_input.get("tool_input", {}), indent=2, ensure_ascii=False)

    # Auto-approve safe tools
    if tool_name in SAFE_TOOLS:
        output({"decision": "approve"})
        return

    # Check if bridge is running
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            pass
    except Exception:
        # Bridge not running, approve by default (don't block work)
        output({"decision": "approve"})
        return

    # Check auto-approve for this agent's session
    if tool_name not in CRITICAL_TOOLS:
        try:
            data = json.dumps({"agent_id": AGENT_ID}).encode()
            req = urllib.request.Request(
                f"{BRIDGE_URL}/check_auto_approve",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
                if result.get("auto_approve"):
                    output({"decision": "approve"})
                    return
        except Exception:
            pass

    # Request approval via Telegram
    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "tool_name": tool_name,
            "tool_input": tool_input[:2000],  # Truncate large inputs
            "description": f"L'agent veut utiliser {tool_name}",
            "timeout": 300,
        }).encode()

        req = urllib.request.Request(
            f"{BRIDGE_URL}/approve",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=310) as resp:
            result = json.loads(resp.read())
            decision = result.get("decision", "deny")
            output({"decision": decision})
            return

    except urllib.error.URLError as e:
        # Network error, approve by default
        sys.stderr.write(f"Bridge error: {e}\n")
        output({"decision": "approve"})
    except Exception as e:
        sys.stderr.write(f"Hook error: {e}\n")
        output({"decision": "approve"})


def output(data: dict):
    """Output JSON to stdout for Claude Code."""
    print(json.dumps(data))


if __name__ == "__main__":
    main()
