# 🤖 Claude Code ↔ Telegram Bridge

Communication **bidirectionnelle** entre tes agents Claude Code et Telegram.

## Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| 📩 Notifications | Reçois les notifications des agents en temps réel |
| 🔐 Approbations | Approuve/refuse les actions sensibles via boutons inline |
| 💬 Messages | Envoie des instructions à tes agents |
| 🤖 Multi-agents | Gère plusieurs agents/sous-agents simultanément |
| ⚡ Auto-approve | Active l'auto-approbation par session pour aller plus vite |
| ⏸️ Pause/Resume | Bascule entre contrôle Telegram et travail local |

## Architecture

```
Claude Code Agent ──hook──→ Hook Script ──HTTP──→ Bridge Server ──API──→ Telegram
                                                       ↑                    │
                                                       └────── réponse ─────┘
```

## Installation

### 1. Prérequis

- Python 3.10+
- Un bot Telegram (créé via [@BotFather](https://t.me/BotFather))
- Ton Chat ID Telegram (obtenu via [@userinfobot](https://t.me/userinfobot))

### 2. Setup

```bash
cd claude-telegram-bridge
pip install -r requirements.txt
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

Édite `~/.claude/settings.json` (Windows: `C:\Users\<TON_USER>\.claude\settings.json`) :

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /chemin/vers/claude-telegram-bridge/hooks/hook_pre_tool_use.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /chemin/vers/claude-telegram-bridge/hooks/hook_post_tool_use.py"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /chemin/vers/claude-telegram-bridge/hooks/hook_notification.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /chemin/vers/claude-telegram-bridge/hooks/hook_stop.py"
          }
        ]
      }
    ]
  }
}
```

> **Note Windows:** Remplace `/chemin/vers/` par ton chemin avec des forward slashes.
> Exemple: `C:/Users/Admin/WebstormProjects/claude-telegram-bridge/hooks/...`

### 5. Lancer

```bash
# Linux/Mac
./start.sh

# Windows
python src/bridge_server.py
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
| `/pause` | Approbations sur le terminal |
| `/resume` | Approbations sur Telegram |
| `/shutdown confirm` | Arrêter le bridge |

### 💬 Comment envoyer des messages à Claude

**⚠️ Important:** Les messages sont transmis à Claude **lors de la prochaine demande d'approbation**.

#### Méthode 1 : Répondre à une demande d'approbation (recommandé)

1. Tu reçois une demande d'approbation sur Telegram
2. **Réponds directement** à ce message avec tes instructions
3. Le message est transmis ET l'action est approuvée automatiquement
4. Claude voit tes instructions dans le terminal

```
[Demande d'approbation de Claude]
    ↓
[Tu réponds: "Concentre-toi sur les tests unitaires"]
    ↓
✅ Approuvé avec instructions!
```

#### Méthode 2 : Utiliser /msg (file d'attente)

```
/msg main Fais d'abord les tests du module auth
```

Le message est mis en file d'attente et sera :
- Affiché dans la prochaine demande d'approbation
- Transmis à Claude quand tu approuves

#### Pourquoi ça fonctionne ainsi ?

Claude Code est un processus interactif. On ne peut pas "injecter" du texte pendant qu'il travaille. Les hooks ne se déclenchent que quand Claude fait une action. C'est pourquoi les messages sont livrés au moment des approbations.

### Flux d'approbation

1. Claude veut exécuter `bash` → le hook s'active
2. Tu reçois un message Telegram avec :
   - Les détails de l'action
   - Les messages en attente (si tu as utilisé `/msg`)
   - 3 boutons : Approuver / Refuser / Approuver tout
   - La possibilité de répondre avec des instructions
3. Tu choisis une action ou tu réponds avec des instructions
4. Claude continue avec tes instructions visibles dans le terminal

## Modes de fonctionnement

### Option 1 : Commandes Telegram (recommandé)

```
/pause   → Les approbations passent sur le terminal (comportement natif Claude Code)
/resume  → Les approbations reviennent sur Telegram
```

**Avec /pause :**
- Tu vois les demandes d'approbation dans le terminal
- Tu réponds directement dans le terminal (y/n, etc.)
- Le bridge reste actif mais n'intercepte plus les approbations

### Option 2 : Variable d'environnement

**Windows (PowerShell):**
```powershell
$env:CLAUDE_BRIDGE_MODE="local"; claude    # Bypass complet
$env:CLAUDE_BRIDGE_MODE="notify"; claude   # Notifie mais n'attend pas
$env:CLAUDE_BRIDGE_MODE="telegram"; claude # Approbations complètes (défaut)
```

**Linux/Mac:**
```bash
CLAUDE_BRIDGE_MODE=local claude
```

### Option 3 : Bridge éteint = mode local automatique

Si le bridge n'est pas lancé, les hooks font un auto-approve automatique.

## Multi-agents

Pour identifier plusieurs agents :

```powershell
# Terminal 1
$env:CLAUDE_AGENT_ID="main"; claude

# Terminal 2
$env:CLAUDE_AGENT_ID="tests"; $env:CLAUDE_AGENT_NAME="Agent Tests"; claude
```

Sur Telegram :
```
/agents
/msg tests Lance les tests du module auth
```

## API du Bridge

| Endpoint | Méthode | Description |
|---|---|---|
| `/notify` | POST | Envoyer une notification |
| `/approve` | POST | Demander une approbation (bloquant) |
| `/status` | GET | Health check |
