# WODpilot – KI-gestützter CrossFit Remote Coach

WODpilot ist ein Telegram-Bot und Admin-Dashboard für personalisiertes CrossFit-Coaching. Der Bot verwendet einen KI-Agenten (pi-agent, Anthropic Claude), der die Trainingsbelastung des Athleten aus Garmin-Daten analysiert, WODs von verschiedenen CrossFit-Boxen abruft und individuelles Coaching-Feedback gibt.

## Features

- **Telegram Bot** – Konversationsbasiertes Coaching, Sprachnachrichten, Bild-/Videoanalyse, Morgen-Briefings
- **Athleten-Dashboard** – Wochenplan einsehen, Ergebnisse eintragen, Trainingspräferenzen pflegen
- **Wochenplanung** – Sonntags fragt der Coach nach Terminen und plant die Woche
- **Garmin Integration** – Automatische Synchronisation von Aktivitäten, ATL/CTL/TSB-Berechnung
- **WOD Scraper** – Tägliche WODs von konfigurierbaren CrossFit-Box-Webseiten
- **4-stufiges Memory-System** – Working Memory, Semantic Memory (pgvector), Episodic Memory, Procedural Memory
- **BYOK (Bring Your Own Key)** – Jeder User verwendet seinen eigenen Anthropic API-Key
- **Admin Dashboard** – Flask-basiertes Web-UI für User-Management, Invite-Codes, WOD-Verwaltung
- **DSGVO-konform** – Einwilligungsabfrage bei Registrierung, vollständige Datenlöschung via /delete

## Architektur

```
Telegram User
     │
     ▼
Python Bot (python-telegram-bot)
     │  HTTP POST /chat, /briefing, /analyze
     ▼
Pi-Agent Service (Node.js + pi-agent)
     │  HTTP /api/tools/*
     ▼
Python Tools API (Flask)
     │
     ▼
Supabase (PostgreSQL + pgvector) / Garmin Connect / WOD Sources
```

**Services:**
| Service | Technologie | Port |
|---------|-------------|------|
| Telegram Bot | Python, python-telegram-bot | – |
| Web / Admin + Tools API | Python, Flask | 8080 |
| Pi-Agent LLM Service | Node.js, pi-agent-core | 3001 |
| Reverse Proxy | Traefik v3 | 80/443 |
| Database | Supabase (PostgreSQL + pgvector) | – |

## Voraussetzungen

- Docker & Docker Compose
- Supabase-Projekt (kostenlos verfügbar)
- Telegram Bot Token (von [@BotFather](https://t.me/BotFather))
- Anthropic API-Key (für Nutzer, BYOK)
- Hetzner Cloud Account (für Production, optional)

## Quick Start (Lokal)

```bash
# 1. Repository klonen
git clone https://github.com/<owner>/Wodpilot.git
cd Wodpilot

# 2. Umgebungsvariablen konfigurieren
cp .env.example .env
# .env mit deinen Werten befüllen

# 3. Datenbank-Migrationen ausführen
# In Supabase SQL-Editor: db/migrations/001_initial.sql dann 002_vector_search_rpc.sql

# 4. Services starten
docker compose up --build

# 5. Ersten Invite-Code erstellen
# Öffne http://localhost:8080 → Codes → Code erstellen
# Teile den Code mit dem ersten Nutzer, der /start sendet
```

## Environment Variables

| Variable | Beschreibung | Pflicht |
|----------|-------------|---------|
| `TELEGRAM_TOKEN` | Bot-Token von BotFather | ✅ |
| `ADMIN_TELEGRAM_ID` | Telegram-ID des Admins | ✅ |
| `SUPABASE_URL` | Supabase-Projekt-URL | ✅ |
| `SUPABASE_SERVICE_KEY` | Supabase Service-Role-Key | ✅ |
| `ENCRYPTION_KEY` | Fernet-Key für Passwort-Verschlüsselung | ✅ |
| `WEB_SECRET_KEY` | Flask Session Secret | ✅ |
| `WEB_ADMIN_PASSWORD` | Admin Dashboard Passwort | ✅ |
| `DOMAIN` | Domain für Traefik/Let's Encrypt | ✅ |
| `ACME_EMAIL` | E-Mail für Let's Encrypt | ✅ |
| `INTERNAL_API_TOKEN` | Shared Secret zwischen Web und pi-agent | ✅ |
| `OPENAI_API_KEY` | OpenAI-Key für pgvector-Embeddings | optional |
| `DEFAULT_LLM_MODEL` | Standard-Modell (default: claude-sonnet-4-20250514) | optional |
| `MAX_API_CALLS_PER_DAY` | Rate-Limit pro User/Tag (default: 50) | optional |

Encryption-Key generieren:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Internal API Token generieren:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Telegram Bot Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `/start` | Registrierung mit Invite-Code |
| `/help` | Hilfe und Befehlsübersicht |
| `/status` | Aktueller Trainingsstatus (ATL/CTL/TSB) |
| `/prs` | Personal Records |
| `/wod` | Heutiges WOD |
| `/briefing` | Morgendliches Briefing |
| `/dashboard` | Login-Link zum persönlichen Wochenplan |
| `/replan` | Kommende Woche planen (optionale Vorgaben als Argument) |
| `/settings` | Einstellungen |
| `/delete` | Account löschen (DSGVO) |

Zusätzlich: Freitext-Nachrichten, Sprachnachrichten, Bilder und Videos werden direkt vom
Coach beantwortet. Sprachnachrichten werden transkribiert und wie getippte Nachrichten
behandelt – auch Trainingsergebnisse lassen sich so einsprechen.

## Garmin Integration

1. Nutzer trägt Garmin-E-Mail und -Passwort bei der Registrierung ein
2. Passwort wird mit Fernet AES-128 verschlüsselt gespeichert
3. Täglicher Sync um 05:00 Uhr (APScheduler)
4. TSS-Berechnung: `duration_h × (hr_ratio)² × 100`
5. ATL (7d EMA), CTL (42d EMA), TSB = CTL - ATL

## Production Deployment

Voraussetzungen: GitHub Secrets müssen gesetzt sein (siehe `.env.example`).

```bash
# Terraform (einmalig – VPS provisionieren)
# Via GitHub Actions → Terraform Workflow → apply

# CI/CD
# Push auf main → automatisches Deployment via GitHub Actions
```

Benötigte GitHub Secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `HCLOUD_TOKEN` und alle `.env`-Variablen.

## Lizenz

MIT
