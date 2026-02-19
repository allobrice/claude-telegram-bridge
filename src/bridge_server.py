#!/usr/bin/env python3
"""
Claude Code ↔ Telegram Bridge Server
=====================================
Serveur local qui fait le pont entre les hooks Claude Code et Telegram.
- Reçoit les notifications des hooks via HTTP (localhost)
- Envoie les messages/demandes d'approbation sur Telegram
- Attend les réponses utilisateur et les renvoie aux hooks
- Gère plusieurs agents/sous-agents simultanément
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─── Configuration ────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"❌ Config file not found: {CONFIG_PATH}")
        print("   Copy config/config.example.json → config/config.json and fill in your values.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)

CONFIG = load_config()

TELEGRAM_BOT_TOKEN = CONFIG["telegram_bot_token"]
TELEGRAM_CHAT_ID = int(CONFIG["telegram_chat_id"])
BRIDGE_HOST = CONFIG.get("bridge_host", "127.0.0.1")
BRIDGE_PORT = int(CONFIG.get("bridge_port", 7888))
APPROVAL_TIMEOUT = int(CONFIG.get("approval_timeout_seconds", 300))  # 5 min default

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bridge")

# ─── State Management ─────────────────────────────────────────────────────────

# Pending approvals: request_id → {event, response, agent_info, ...}
pending_approvals: dict[str, dict] = {}
# Active agent sessions for free-form messaging
active_sessions: dict[str, dict] = {}
# Message queue: agent_id → [messages from user]
message_queues: dict[str, list[str]] = {}
# Map message_id → request_id for reply handling
message_to_request: dict[int, str] = {}
# Lock for thread-safe access
state_lock = asyncio.Lock()
# Global pause mode (auto-approve everything)
bridge_paused: bool = False

# Reference to the Telegram bot for sending from FastAPI routes
telegram_app: Optional[Application] = None

# ─── FastAPI (HTTP API for hooks) ─────────────────────────────────────────────

api = FastAPI(title="Claude Code ↔ Telegram Bridge")


class NotificationRequest(BaseModel):
    """Simple notification (no response needed)."""
    agent_id: str = "main"
    agent_name: str = "Claude Code"
    message: str
    level: str = "info"  # info, success, warning, error


class ApprovalRequest(BaseModel):
    """Request requiring user approval."""
    agent_id: str = "main"
    agent_name: str = "Claude Code"
    tool_name: str
    tool_input: str = ""
    description: str = ""
    timeout: int = APPROVAL_TIMEOUT


class MessagePollRequest(BaseModel):
    """Poll for user messages sent to a specific agent."""
    agent_id: str = "main"
    timeout: int = 30


LEVEL_EMOJI = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "task_complete": "🏁",
}


@api.post("/notify")
async def notify(req: NotificationRequest):
    """Send a notification to Telegram (fire-and-forget)."""
    emoji = LEVEL_EMOJI.get(req.level, "📌")
    text = (
        f"{emoji} *{_escape_md(req.agent_name)}*\n\n"
        f"{_escape_md(req.message)}"
    )
    try:
        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="MarkdownV2",
        )
        return {"status": "sent"}
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        # Retry without markdown
        try:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"{emoji} {req.agent_name}\n\n{req.message}",
            )
            return {"status": "sent_plain"}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))


@api.post("/approve")
async def request_approval(req: ApprovalRequest):
    """
    Send an approval request to Telegram and WAIT for the user's response.
    This endpoint blocks until the user approves/denies or timeout is reached.
    """
    global bridge_paused
    
    # If bridge is paused, signal the hook to let Claude Code handle it natively
    if bridge_paused:
        return {"decision": "passthrough", "reason": "bridge_paused"}
    
    request_id = str(uuid.uuid4())[:8]
    
    # Check for pending messages for this agent
    pending_messages = []
    async with state_lock:
        if req.agent_id in message_queues and message_queues[req.agent_id]:
            pending_messages = message_queues[req.agent_id].copy()

    # Build the Telegram message
    tool_input_display = req.tool_input[:500] + "..." if len(req.tool_input) > 500 else req.tool_input
    text = (
        f"🔐 *Approbation requise*\n\n"
        f"*Agent:* {_escape_md(req.agent_name)}\n"
        f"*Outil:* `{_escape_md(req.tool_name)}`\n"
    )
    if req.description:
        text += f"*Description:* {_escape_md(req.description)}\n"
    if tool_input_display:
        text += f"\n```\n{_escape_md(tool_input_display)}\n```\n"
    
    # Show pending messages if any
    if pending_messages:
        text += f"\n📨 *Messages en attente:*\n"
        for msg in pending_messages[-3:]:  # Show last 3
            text += f"• {_escape_md(msg[:100])}\n"
    
    text += f"\n_ID: {request_id}_\n"
    text += f"_💡 Réponds à ce message pour envoyer des instructions_"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approuver", callback_data=f"approve:{request_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"deny:{request_id}"),
        ],
        [
            InlineKeyboardButton("✅ Approuver tout (session)", callback_data=f"approve_all:{request_id}"),
        ],
    ])

    # Store pending approval
    approval_event = asyncio.Event()
    async with state_lock:
        pending_approvals[request_id] = {
            "event": approval_event,
            "response": None,
            "reason": "",
            "user_message": "",
            "agent_id": req.agent_id,
            "agent_name": req.agent_name,
            "tool_name": req.tool_name,
            "created_at": time.time(),
        }

    sent_message = None
    try:
        sent_message = await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )
    except Exception:
        # Fallback without markdown
        plain = (
            f"🔐 Approbation requise\n\n"
            f"Agent: {req.agent_name}\n"
            f"Outil: {req.tool_name}\n"
        )
        if req.description:
            plain += f"Description: {req.description}\n"
        if tool_input_display:
            plain += f"\nInput:\n{tool_input_display}\n"
        if pending_messages:
            plain += f"\n📨 Messages en attente:\n"
            for msg in pending_messages[-3:]:
                plain += f"• {msg[:100]}\n"
        plain += f"\nID: {request_id}"
        plain += f"\n💡 Réponds à ce message pour envoyer des instructions"
        sent_message = await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=plain,
            reply_markup=keyboard,
        )

    # Map this message to the request for reply handling
    if sent_message:
        async with state_lock:
            message_to_request[sent_message.message_id] = request_id

    # Wait for user response
    try:
        await asyncio.wait_for(approval_event.wait(), timeout=req.timeout)
    except asyncio.TimeoutError:
        async with state_lock:
            pending_approvals.pop(request_id, None)
            if sent_message:
                message_to_request.pop(sent_message.message_id, None)
        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⏰ Approbation {request_id} expirée (timeout {req.timeout}s). Refus par défaut.",
        )
        return {"decision": "deny", "reason": "timeout"}

    async with state_lock:
        result = pending_approvals.pop(request_id, {})
        if sent_message:
            message_to_request.pop(sent_message.message_id, None)
        # Clear pending messages now that they've been delivered
        if req.agent_id in message_queues:
            message_queues[req.agent_id].clear()

    response = result.get("response", "deny")
    reason = result.get("reason", "")
    user_message = result.get("user_message", "")
    
    # Include pending messages + any reply in the reason
    all_messages = pending_messages + ([user_message] if user_message else [])
    if all_messages:
        reason = f"{reason}\n\nUser instructions:\n" + "\n".join(all_messages)

    return {"decision": response, "reason": reason, "request_id": request_id}


@api.post("/send_message")
async def send_message_to_agent(req: dict):
    """
    Endpoint for hooks to poll for user messages.
    The hook can call this to check if the user sent a message for a specific agent.
    """
    agent_id = req.get("agent_id", "main")
    timeout = min(req.get("timeout", 30), 120)

    # Check if there are already queued messages
    async with state_lock:
        if agent_id in message_queues and message_queues[agent_id]:
            messages = message_queues[agent_id].copy()
            message_queues[agent_id].clear()
            return {"messages": messages}

    # Wait for new messages
    start = time.time()
    while time.time() - start < timeout:
        await asyncio.sleep(1)
        async with state_lock:
            if agent_id in message_queues and message_queues[agent_id]:
                messages = message_queues[agent_id].copy()
                message_queues[agent_id].clear()
                return {"messages": messages}

    return {"messages": []}


@api.get("/status")
async def status():
    """Health check + current state."""
    async with state_lock:
        return {
            "status": "running",
            "paused": bridge_paused,
            "pending_approvals": len(pending_approvals),
            "active_sessions": list(active_sessions.keys()),
            "message_queues": {k: len(v) for k, v in message_queues.items()},
            "uptime": datetime.now(timezone.utc).isoformat(),
        }


# ─── Telegram Bot Handlers ───────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        await update.message.reply_text("⛔ Non autorisé.")
        return
    await update.message.reply_text(
        "🤖 *Claude Code Bridge* est actif\\!\n\n"
        "*Commandes:*\n"
        "/status \\- État du bridge\n"
        "/agents \\- Agents actifs\n"
        "/msg `agent_id` `message` \\- Envoyer un message à un agent\n"
        "/pending \\- Approbations en attente\n"
        "/approve\\_all \\- Tout approuver\n"
        "/deny\\_all \\- Tout refuser\n"
        "/pause \\- Approbations sur le terminal\n"
        "/resume \\- Approbations sur Telegram\n"
        "/shutdown \\- Arrêter le bridge\n\n"
        "*💡 Astuce:* Réponds directement à une demande d'approbation pour envoyer des instructions à l'agent\\!",
        parse_mode="MarkdownV2",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    async with state_lock:
        pause_status = "⏸️ PAUSE (terminal)" if bridge_paused else "▶️ ACTIF (telegram)"
        pending_list = ""
        if pending_approvals:
            pending_list = "\n\n*Approbations en attente:*\n"
            for rid, info in pending_approvals.items():
                age = int(time.time() - info["created_at"])
                pending_list += f"• `{rid}` {info['tool_name']} ({age}s)\n"
        
        queued = sum(len(v) for v in message_queues.values())
        text = (
            f"📊 *Bridge Status*\n\n"
            f"• Mode: {pause_status}\n"
            f"• Approbations en attente: {len(pending_approvals)}\n"
            f"• Sessions actives: {len(active_sessions)}\n"
            f"• Messages en file: {queued}"
            f"{pending_list}"
        )
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except:
        await update.message.reply_text(text.replace("*", "").replace("`", ""))


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agents command."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    async with state_lock:
        if not active_sessions:
            await update.message.reply_text("Aucun agent actif.\n\nL'agent s'enregistre automatiquement lors de sa première action.")
            return
        lines = ["🤖 Agents actifs:\n"]
        for aid, info in active_sessions.items():
            lines.append(f"• {info.get('name', aid)} (id: `{aid}`)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /msg <agent_id> <message> command."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/msg <agent_id> <message>`\n\n"
            "Exemple: `/msg main Concentre-toi sur les tests`\n\n"
            "💡 Ou réponds directement à une demande d'approbation!",
            parse_mode="Markdown"
        )
        return
    agent_id = args[0]
    message = " ".join(args[1:])
    async with state_lock:
        if agent_id not in message_queues:
            message_queues[agent_id] = []
        message_queues[agent_id].append(message)
        queue_size = len(message_queues[agent_id])
    await update.message.reply_text(
        f"📨 Message ajouté à la file de `{agent_id}` ({queue_size} en attente)\n\n"
        f"_Le message sera transmis lors de la prochaine demande d'approbation._",
        parse_mode="Markdown"
    )


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pending command."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    async with state_lock:
        if not pending_approvals:
            await update.message.reply_text("✅ Aucune approbation en attente.")
            return
        lines = ["🔐 Approbations en attente:\n"]
        for rid, info in pending_approvals.items():
            age = int(time.time() - info["created_at"])
            lines.append(
                f"• [{rid}] {info['agent_name']} → {info['tool_name']} ({age}s)"
            )
    await update.message.reply_text("\n".join(lines))


async def cmd_approve_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve all pending requests."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    async with state_lock:
        count = len(pending_approvals)
        for rid, info in pending_approvals.items():
            info["response"] = "approve"
            info["reason"] = "bulk approved"
            info["event"].set()
    await update.message.reply_text(f"✅ {count} approbation(s) approuvée(s).")


async def cmd_deny_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deny all pending requests."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    async with state_lock:
        count = len(pending_approvals)
        for rid, info in pending_approvals.items():
            info["response"] = "deny"
            info["reason"] = "bulk denied"
            info["event"].set()
    await update.message.reply_text(f"❌ {count} approbation(s) refusée(s).")


async def cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /shutdown command - stops the bridge server."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        await update.message.reply_text("⛔ Non autorisé.")
        return
    
    # Check for confirmation
    if context.args and context.args[0].lower() == "confirm":
        await update.message.reply_text("🔴 Arrêt du bridge en cours...")
        # Schedule shutdown
        asyncio.get_event_loop().call_later(1, lambda: os._exit(0))
    else:
        await update.message.reply_text(
            "⚠️ Es-tu sûr de vouloir arrêter le bridge?\n\n"
            "Tape `/shutdown confirm` pour confirmer.",
            parse_mode="Markdown"
        )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command - return control to terminal."""
    global bridge_paused
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    
    bridge_paused = True
    await update.message.reply_text(
        "⏸️ Bridge en PAUSE\n\n"
        "Les approbations sont maintenant gérées dans le terminal.\n"
        "Tu peux interagir directement avec Claude Code.\n\n"
        "Tape /resume pour reprendre le contrôle sur Telegram."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command - re-enable Telegram approvals."""
    global bridge_paused
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    
    bridge_paused = False
    await update.message.reply_text(
        "▶️ Bridge ACTIF\n\n"
        "Les demandes d'approbation seront envoyées sur Telegram."
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses (approve/deny)."""
    query = update.callback_query
    if query.message.chat.id != TELEGRAM_CHAT_ID:
        await query.answer("Non autorisé", show_alert=True)
        return

    data = query.data
    action, request_id = data.split(":", 1)

    async with state_lock:
        if request_id not in pending_approvals:
            await query.answer("⚠️ Requête expirée ou déjà traitée", show_alert=True)
            return

        info = pending_approvals[request_id]

        if action == "approve":
            info["response"] = "approve"
            info["reason"] = "user approved"
            info["event"].set()
            await query.answer("✅ Approuvé!")
            await query.edit_message_text(
                text=query.message.text + "\n\n✅ APPROUVÉ",
            )

        elif action == "deny":
            info["response"] = "deny"
            info["reason"] = "user denied"
            info["event"].set()
            await query.answer("❌ Refusé!")
            await query.edit_message_text(
                text=query.message.text + "\n\n❌ REFUSÉ",
            )

        elif action == "approve_all":
            # Approve this + set auto-approve for the agent's session
            info["response"] = "approve"
            info["reason"] = "user approved (session auto-approve enabled)"
            info["event"].set()
            agent_id = info["agent_id"]
            active_sessions[agent_id] = {
                **active_sessions.get(agent_id, {}),
                "auto_approve": True,
                "name": info["agent_name"],
            }
            await query.answer("✅ Approuvé! Auto-approbation activée pour cette session.")
            await query.edit_message_text(
                text=query.message.text + "\n\n✅ APPROUVÉ (auto-approve ON)",
            )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle free-form text messages.
    If it's a reply to an approval request, include it in the approval response.
    Otherwise, route to the appropriate agent's message queue.
    """
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return

    text = update.message.text
    
    # Check if it's a reply to an approval request
    if update.message.reply_to_message:
        reply_msg_id = update.message.reply_to_message.message_id
        async with state_lock:
            if reply_msg_id in message_to_request:
                request_id = message_to_request[reply_msg_id]
                if request_id in pending_approvals:
                    info = pending_approvals[request_id]
                    info["user_message"] = text
                    info["response"] = "approve"
                    info["reason"] = "approved with instructions"
                    info["event"].set()
                    await update.message.reply_text(
                        f"✅ Approuvé avec instructions!\n\n"
                        f"Message transmis: _{text[:100]}{'...' if len(text) > 100 else ''}_",
                        parse_mode="Markdown"
                    )
                    return

    # Otherwise, queue for the agent
    agent_id = "main"  # Default

    # Check if it's a reply to a bot message containing an agent ID
    if update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot:
        reply_text = update.message.reply_to_message.text or ""
        # Try to extract agent_id from the original message
        for aid in list(active_sessions.keys()) + ["main"]:
            if aid in reply_text:
                agent_id = aid
                break

    async with state_lock:
        if agent_id not in message_queues:
            message_queues[agent_id] = []
        message_queues[agent_id].append(text)
        queue_size = len(message_queues[agent_id])

    await update.message.reply_text(
        f"📨 Message ajouté à la file de `{agent_id}` ({queue_size} en attente)\n\n"
        f"_Sera transmis à la prochaine demande d'approbation._",
        parse_mode="Markdown"
    )


# ─── Auto-approve check ──────────────────────────────────────────────────────

@api.post("/check_auto_approve")
async def check_auto_approve(req: dict):
    """Check if an agent has auto-approve enabled."""
    agent_id = req.get("agent_id", "main")
    async with state_lock:
        session = active_sessions.get(agent_id, {})
        return {"auto_approve": session.get("auto_approve", False)}


@api.post("/register_agent")
async def register_agent(req: dict):
    """Register an agent session."""
    agent_id = req.get("agent_id", "main")
    agent_name = req.get("agent_name", "Claude Code")
    async with state_lock:
        active_sessions[agent_id] = {
            "name": agent_name,
            "registered_at": time.time(),
            "auto_approve": False,
        }
        if agent_id not in message_queues:
            message_queues[agent_id] = []
    logger.info(f"Agent registered: {agent_id} ({agent_name})")
    return {"status": "registered"}


@api.post("/unregister_agent")
async def unregister_agent(req: dict):
    """Unregister an agent session."""
    agent_id = req.get("agent_id", "main")
    async with state_lock:
        active_sessions.pop(agent_id, None)
        message_queues.pop(agent_id, None)
    logger.info(f"Agent unregistered: {agent_id}")
    return {"status": "unregistered"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!\\"
    result = ""
    for char in text:
        if char in special_chars:
            result += f"\\{char}"
        else:
            result += char
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_both():
    """Run both the Telegram bot and the FastAPI server concurrently."""
    global telegram_app

    # Build Telegram bot
    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Register handlers
    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("status", cmd_status))
    telegram_app.add_handler(CommandHandler("agents", cmd_agents))
    telegram_app.add_handler(CommandHandler("msg", cmd_msg))
    telegram_app.add_handler(CommandHandler("pending", cmd_pending))
    telegram_app.add_handler(CommandHandler("approve_all", cmd_approve_all))
    telegram_app.add_handler(CommandHandler("deny_all", cmd_deny_all))
    telegram_app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    telegram_app.add_handler(CommandHandler("pause", cmd_pause))
    telegram_app.add_handler(CommandHandler("resume", cmd_resume))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Initialize bot
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    logger.info(f"🤖 Telegram bot started")
    logger.info(f"🌐 Bridge API starting on {BRIDGE_HOST}:{BRIDGE_PORT}")

    # Send startup notification
    try:
        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🟢 Claude Code Bridge démarré et prêt!\n\n💡 Réponds à une demande d'approbation pour envoyer des instructions.",
        )
    except Exception as e:
        logger.warning(f"Could not send startup message: {e}")

    # Run FastAPI
    config = uvicorn.Config(api, host=BRIDGE_HOST, port=BRIDGE_PORT, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


if __name__ == "__main__":
    asyncio.run(run_both())
