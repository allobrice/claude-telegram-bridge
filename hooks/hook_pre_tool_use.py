#!/usr/bin/env python3
"""
Claude Code Hook: PreToolUse - With message delivery
"""

import json
import os
import sys
import urllib.request
import urllib.error

BRIDGE_URL = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:7888")
AGENT_ID = os.environ.get("CLAUDE_AGENT_ID", "main")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "Claude Code")
BRIDGE_MODE = os.environ.get("CLAUDE_BRIDGE_MODE", "telegram").lower()

CRITICAL_TOOLS = {"bash", "write", "edit", "execute"}
SAFE_TOOLS = {"read", "list_files", "search", "grep", "glob", "view"}

def main():
    if BRIDGE_MODE == "local":
        return

    raw = sys.stdin.read().strip()
    if not raw:
        output({"decision": "approve"})
        return

    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        output({"decision": "approve"})
        return

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = json.dumps(hook_input.get("tool_input", {}), indent=2, ensure_ascii=False)

    if tool_name in SAFE_TOOLS:
        output({"decision": "approve"})
        return

    bridge_available = False
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            bridge_available = True
    except Exception:
        pass

    if not bridge_available:
        output({"decision": "approve"})
        return

    if BRIDGE_MODE == "notify":
        try:
            payload = json.dumps({
                "agent_id": AGENT_ID,
                "agent_name": AGENT_NAME,
                "message": f"🔧 Outil: {tool_name}\n\n{tool_input[:500]}",
                "level": "info",
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
        output({"decision": "approve"})
        return

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

    try:
        payload = json.dumps({
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "tool_name": tool_name,
            "tool_input": tool_input[:2000],
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
            reason = result.get("reason", "")
            
            # If bridge is paused, don't output anything - let Claude Code handle it natively
            if decision == "passthrough":
                return
            
            # If user sent instructions, print them to stderr so Claude sees them
            if "User instructions:" in reason:
                instructions = reason.split("User instructions:")[1].strip()
                sys.stderr.write(f"\n{'='*50}\n")
                sys.stderr.write(f"📨 INSTRUCTIONS UTILISATEUR:\n{instructions}\n")
                sys.stderr.write(f"{'='*50}\n\n")
            
            output({"decision": decision})
            return

    except urllib.error.URLError as e:
        sys.stderr.write(f"Bridge error: {e}\n")
        output({"decision": "approve"})
    except Exception as e:
        sys.stderr.write(f"Hook error: {e}\n")
        output({"decision": "approve"})

def output(data: dict):
    print(json.dumps(data))

if __name__ == "__main__":
    main()
