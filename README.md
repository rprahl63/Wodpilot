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
| Database | Postgres + PostgREST (pgvector), lokal auf dem NAS | – |

## Voraussetzungen

- Docker & Docker Compose
- Telegram Bot Token (von [@BotFather](https://t.me/BotFather))
- Requesty API-Key (pro Nutzer, BYOK – deckt Chat, Embeddings und Transkription ab)

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
| `BIND_IP` | NetBird-IP, an die das Dashboard bindet | ✅ |
| `INTERNAL_API_TOKEN` | Shared Secret zwischen Web und pi-agent | ✅ |
| `DASHBOARD_BASE_URL` | Basis-URL der Magic Links (default: `http://$BIND_IP:8080`) | optional |
| `DEFAULT_LLM_MODEL` | Standard-Modell (default: anthropic/claude-sonnet-4-5) | optional |
| `TRANSCRIPTION_MODEL` | Sprachnachrichten (default: openai/gpt-4o-mini-transcribe) | optional |
| `MAX_API_CALLS_PER_DAY` | Rate-Limit pro User/Tag (default: 50) | optional |

Die vollständige Liste für das NAS-Deployment steht in `deploy/nas/.env.example`.

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

## Deployment

WODpilot läuft auf einer **Synology DS218+ im LAN** – kein Cloud-Hosting, kein
CI/CD, keine öffentliche Domain. Images werden lokal auf dem NAS gebaut, das
Dashboard ist nur über NetBird erreichbar, der Bot arbeitet per Long Polling.

Ablauf und Betrieb: **[`deploy/nas/README.md`](deploy/nas/README.md)**.
Kurzfassung – erst Schema, dann Container:

```bash
ssh nas && cd /volume1/docker/wodpilot && git pull
cd deploy/nas
docker compose exec -T db psql -U wodpilot -d wodpilot < ../../db/migrations/<neue>.sql
docker compose build && docker compose up -d
```

## Lizenz

MIT
