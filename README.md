# 🤖 Claude Code ↔ Telegram Bridge

Communication **bidirectionnelle** entre tes agents Claude Code et Telegram.

## Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| 📩 Notifications | Reçois les notifications des agents en temps réel |
| 🔐 Approbations | Approuve/refuse les actions sensibles via boutons inline |
| 💬 Messages | Envoie des messages/instructions à tes agents |
| 🤖 Multi-agents | Gère plusieurs agents/sous-agents simultanément |
| ⚡ Auto-approve | Active l'auto-approbation par session pour aller plus vite |
| 🏁 Lifecycle | Notifications de démarrage/arrêt des agents |

## Architecture

```
Claude Code Agent ──hook──→ Hook Script ──HTTP──→ Bridge Server ──API──→ Telegram
                                                       ↑                    │
                                                       └────── réponse ─────┘
```

Le **Bridge Server** tourne en local (`127.0.0.1:7888`) et combine :
- Un **serveur HTTP** (FastAPI) qui reçoit les requêtes des hooks
- Un **bot Telegram** (long polling) qui communique avec toi

> ⚠️ Pas besoin d'IP publique ni de port ouvert. Le long polling Telegram fonctionne derrière un NAT/firewall.

## Installation

### 1. Prérequis

- Python 3.10+
- Un bot Telegram (créé via [@BotFather](https://t.me/BotFather))
- Ton Chat ID Telegram (obtenu via [@userinfobot](https://t.me/userinfobot))

### 2. Setup

```bash
# Cloner/copier le projet
cd claude-telegram-bridge

# Installer les dépendances
pip3 install -r requirements.txt

# Configurer
cp config/config.example.json config/config.json
# Éditer config.json avec ton token bot et chat ID
```

### 3. Configuration (`config/config.json`)

```json
{
  "telegram_bot_token": "7123456789:AAH...",
  "telegram_chat_id": 123456789,
  "bridge_host": "127.0.0.1",
  "bridge_port": 7888,
  "approval_timeout_seconds": 300
}
```

### 4. Configurer les hooks Claude Code

Édite `~/.claude/settings.json` :

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python3 /chemin/absolu/vers/claude-telegram-bridge/hooks/hook_pre_tool_use.py"
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "python3 /chemin/absolu/vers/claude-telegram-bridge/hooks/hook_post_tool_use.py"
      }
    ],
    "Notification": [
      {
        "type": "command",
        "command": "python3 /chemin/absolu/vers/claude-telegram-bridge/hooks/hook_notification.py"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python3 /chemin/absolu/vers/claude-telegram-bridge/hooks/hook_stop.py"
      }
    ]
  }
}
```

### 5. Lancer

```bash
# Terminal dédié (ou tmux/screen/systemd)
./start.sh
```

## Utilisation

### Commandes Telegram

| Commande | Description |
|---|---|
| `/start` | Affiche l'aide |
| `/status` | État du bridge |
| `/agents` | Liste les agents actifs |
| `/pending` | Approbations en attente |
| `/msg <agent_id> <message>` | Envoyer un message à un agent |
| `/approve_all` | Approuver toutes les demandes en attente |
| `/deny_all` | Refuser toutes les demandes en attente |

### Flux d'approbation

1. L'agent veut exécuter `bash` → le hook `PreToolUse` s'active
2. Tu reçois un message Telegram avec 3 boutons :
   - **✅ Approuver** — approuve cette action
   - **❌ Refuser** — refuse cette action
   - **✅ Approuver tout (session)** — approuve + active l'auto-approbation pour cet agent
3. L'agent continue ou s'arrête selon ta réponse

### Envoyer un message à un agent

Tu peux répondre directement à un message du bot, ou utiliser :
```
/msg main Concentre-toi sur les tests unitaires d'abord
```

## Variables d'environnement pour sous-agents

Quand tu lances des sous-agents, passe des variables pour les identifier :

```bash
CLAUDE_AGENT_ID=subagent-tests CLAUDE_AGENT_NAME="Agent Tests" claude code ...
```

## Personnalisation des hooks

### Outils safe (jamais d'approbation)

Édite `SAFE_TOOLS` dans `hook_pre_tool_use.py` :
```python
SAFE_TOOLS = {"read", "list_files", "search", "grep", "glob", "view"}
```

### Outils critiques (toujours une approbation, même en auto-approve)

```python
CRITICAL_TOOLS = {"bash", "write", "edit", "execute"}
```

## Lancer en arrière-plan

### Avec systemd (Linux)

```ini
# ~/.config/systemd/user/claude-bridge.service
[Unit]
Description=Claude Code Telegram Bridge

[Service]
ExecStart=/chemin/vers/claude-telegram-bridge/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable claude-bridge
systemctl --user start claude-bridge
```

### Avec tmux

```bash
tmux new-session -d -s bridge './start.sh'
```

## API du Bridge

Le bridge expose une API REST sur `localhost:7888` :

| Endpoint | Méthode | Description |
|---|---|---|
| `/notify` | POST | Envoyer une notification |
| `/approve` | POST | Demander une approbation (bloquant) |
| `/check_auto_approve` | POST | Vérifier l'auto-approbation |
| `/send_message` | POST | Récupérer les messages utilisateur |
| `/register_agent` | POST | Enregistrer un agent |
| `/unregister_agent` | POST | Désenregistrer un agent |
| `/status` | GET | Health check |
