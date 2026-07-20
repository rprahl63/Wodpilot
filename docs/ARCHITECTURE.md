# WODpilot – Architektur

## Systemübersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                  Synology DS218+ (LAN, kein Public Port)        │
│                                                                 │
│  ┌──────────┐   NetBird     ┌──────────────────────────────┐   │
│  │ Dashboard│◄──────────────│  Athlet / Admin (VPN-only)   │   │
│  │ :8080    │               └──────────────────────────────┘   │
│  └────┬─────┘                                                   │
│       │                     Telegram: Long Polling, kein Ingress│
│  ┌────▼──────────────────┐                                      │
│  │  Flask Web + Tools API│                                      │
│  │  web/app.py           │                                      │
│  │  - Admin Dashboard    │                                      │
│  │  - /me/* Athleten-UI  │                                      │
│  │  - /api/tools/*       │                                      │
│  └────────┬──────────────┘                                      │
│           │ HTTP :8080/api/tools/*                              │
│  ┌────────▼──────────────┐     ┌────────────────────────────┐  │
│  │  Pi-Agent Service     │     │  Telegram Bot              │  │
│  │  Node.js + pi-agent   │◄────│  bot/handlers.py           │  │
│  │  :3001                │     │  HTTP POST /chat           │  │
│  └───────────────────────┘     └────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
               ┌─────────────────────────┐
               │  Postgres + PostgREST   │
               │  + pgvector (lokal)     │
               └─────────────────────────┘
```

Der Code spricht weiterhin die Supabase-Client-Library; auf dem NAS antwortet
statt der Cloud ein lokales PostgREST hinter einem nginx-Shim. Details und
Begründung: `deploy/nas/README.md`.

## Services

### Telegram Bot (`bot/`)
- **Framework:** python-telegram-bot 21.6
- **Registrierung:** 6-stufiger `ConversationHandler` (INVITE_CODE → CONSENT → GARMIN_EMAIL → GARMIN_PASS → API_KEY → LLM_MODEL)
- **Handler:** Text, Sprachnachrichten, Fotos, Videos, Befehle (/status, /prs, /wod, /briefing, /dashboard, /replan, /settings, /delete)
- **Sprachnachrichten:** `services/transcription.py` transkribiert via Requesty
  (`POST /v1/audio/transcriptions`, BYOK-Key des Athleten). Das Transkript läuft danach
  durch denselben `_process_text`-Pfad wie eine getippte Nachricht – eine gesprochene
  Antwort auf die Sonntagsfrage plant also ebenso die Woche. Telegram liefert OGG/Opus,
  was Requesty direkt akzeptiert; ffmpeg wird dafür nicht gebraucht.
- **Routing:** Alle LLM-Aufrufe gehen via `services/pi_agent_client.py` an den pi-agent Service

### Pi-Agent Service (`pi-agent-service/`)
- **Framework:** [pi-agent](https://github.com/davidondrej/pi-agent) (Node.js/TypeScript)
- **LLM:** Anthropic Claude (BYOK – api_key kommt per Request)
- **Endpoints:**
  - `POST /chat` – Multi-Turn-Konversation mit Tool-Calling
  - `POST /briefing` – Morgendliches Briefing
  - `POST /plan-week` – Wochenplanung (schreibt die Einheiten per `save_week_plan`-Tool)
  - `POST /analyze` – Bild-/Videoanalyse via Vision-API
  - `GET /health` – Health-Check
- **Tools:** 15 Tools, die HTTP-Calls an die Python Tools API machen
- **Stateless:** Conversation History wird per Request übergeben (Python verwaltet Persistenz)

### Flask Web + Tools API (`web/app.py`)
- **Admin Dashboard:** Login, User-Management, Invite-Codes, WOD-Anzeige, Config, manuelle Triggers
- **Athleten-Dashboard** (`web/athlete.py`, Blueprint `/me`): Wochenplan, Ergebniseingabe,
  Trainingspräferenzen. Login per Magic Link aus Telegram (`/dashboard`); die Athleten-Session
  liegt in `session["athlete_user_id"]`, getrennt von der Admin-Session
- **Tools API** (`/api/tools/*`): Interne Routes für den pi-agent Service
  - Authentifizierung via `INTERNAL_API_TOKEN` Bearer-Token
  - Ruft Python-Servicefunktionen auf (garmin, memory, scraper)

### APScheduler Jobs (`services/scheduler.py`)
| Job | Zeit | Funktion |
|-----|------|----------|
| Garmin-Sync | 05:00 | Aktivitäten aller User synchronisieren |
| WOD-Scrape | 05:30 | WODs von allen konfigurierten Boxen scrapen |
| Morning Briefing | 07:00 | Personalisierte Briefings via pi-agent senden |
| Wochenplanung – Frage | So 10:00 | Athleten nach Terminen für die kommende Woche fragen |
| Wochenplanung – Fallback | So 18:00 | Woche für alle planen, die nicht geantwortet haben |

Alle Jobs laufen auf Serverzeit; `users.timezone` wird nicht berücksichtigt.

### Wochenplanung (Sonntags-Flow)

`training_plans.status` ist die State-Machine: `asked → planning → planned | failed`.
Der Übergang `asked → planning` ist ein Conditional Update – dadurch können die
Antwort des Athleten und der 18:00-Fallback-Job dieselbe Woche nie doppelt planen.
Antwortet der Athlet, behandelt `bot/handlers.py` seine Nachricht als Planungs-Input
statt als normalen Chat.

## Memory-System (4-stufig)

```
┌─────────────────────────────────────────────────────┐
│                   Memory System                      │
│                                                     │
│  Working Memory       │  Letzte 20 Nachrichten      │
│  memory/working.py    │  (Supabase: conversation_   │
│                       │   history)                  │
│ ─────────────────────────────────────────────────── │
│  Semantic Memory      │  Fakten über den Athleten   │
│  memory/semantic.py   │  (pgvector KV-Store)        │
│                       │  Cosine-Similarity Search   │
│                       │  OpenAI text-embedding-     │
│                       │  3-small (1536 Dim)         │
│ ─────────────────────────────────────────────────── │
│  Episodic Memory      │  Ereignisse: PRs,           │
│  memory/episodic.py   │  Verletzungen, Achievements │
│                       │  Zeitgestempelt mit         │
│                       │  Metadaten                  │
│ ─────────────────────────────────────────────────── │
│  Procedural Memory    │  Coaching-Stil-Profil       │
│  memory/procedural.py │  (direct/supportive/        │
│                       │   technical/balanced)       │
└─────────────────────────────────────────────────────┘
```

## Trainingsbelastungs-Berechnung

Basierend auf dem TrainingPeaks ATL/CTL/TSB-Modell:

**TSS (Training Stress Score) aus HR:**
```
TSS = duration_h × (avg_hr / hr_threshold)² × 100
```
`hr_threshold` = 0.82 × `hr_max` (Laktatschwellen-Näherung)

**Exponentieller Gleitdurchschnitt:**
```
ATL(t) = ATL(t-1) × (1 - α_ATL) + TSS(t) × α_ATL    # α_ATL = 2/(7+1)
CTL(t) = CTL(t-1) × (1 - α_CTL) + TSS(t) × α_CTL    # α_CTL = 2/(42+1)
TSB(t) = CTL(t) - ATL(t)
```

**Empfehlung (aus `services/training_load.py`):**
| TSB | Zustand | Empfehlung |
|-----|---------|-----------|
| > +5 | Frisch | Intensität steigern |
| -10 bis +5 | Optimal | Normales Training |
| -20 bis -10 | Etwas müde | Intensität moderat reduzieren |
| < -20 | Sehr müde | Aktive Erholung/Ruhetag |

Zusätzlich: Wenn Laufvolumen > 50 km / 14 Tage → Unterkörper entlasten.

## Datenbankschema (Supabase)

Wichtigste Tabellen:

| Tabelle | Beschreibung |
|---------|-------------|
| `users` | Nutzer (telegram_id, garmin_email, llm_api_key_enc, llm_model, hr_max, ...) |
| `activities` | Garmin-Aktivitäten (type, duration_s, avg_hr, tss, distance_m) |
| `wods` | Gescrapte WODs (date, source, content) |
| `coach_memory` | Semantic Memory KV-Store (key, value, embedding vector) |
| `memory_episodes` | Episodic Memory (content, category, metadata, embedding) |
| `procedural_memory` | Coaching-Profil (coaching_style, notes) |
| `conversation_history` | Working Memory (role, content, letzte 20 Msgs) |
| `invite_codes` | Einladungscodes (code, used_by, expires_at) |
| `config` | App-Konfiguration (wod_sources JSON, Cron-Zeiten) |
| `training_preferences` | Freitext-Wochenrhythmus des Athleten (preferences_text) |
| `training_plans` | Wochenplan pro User (week_start, status, constraints_text) |
| `plan_sessions` | Einheiten inkl. Ergebnis (title, description, status, result_text, rpe) |
| `login_tokens` | Magic-Link-Tokens fürs Athleten-Dashboard (token_hash, expires_at) |

SQL-Funktionen:
- `search_coach_memory(user_id, query_embedding, match_count)` – pgvector Cosine Search
- `search_episodes(user_id, query_embedding, match_count)` – pgvector Cosine Search

## Sicherheit

- **Fernet-Verschlüsselung** (AES-128-CBC) für Garmin-Passwörter und LLM API-Keys
- **INTERNAL_API_TOKEN** – Bearer-Token zwischen web und pi-agent (nie öffentlich)
- **GitHub Secrets** – alle Secrets werden als Repository-Secrets verwaltet, nie im Code
- **BYOK** – kein zentraler API-Key; Kosten und Zugangskontrolle beim User
- **Rate Limiting** – `MAX_API_CALLS_PER_DAY` verhindert Kostenexplosion
- **GDPR** – Vollständige Datenlöschung via `/delete` Telegram-Befehl

## Tool-Calling Flow

```
User Message → Python Bot
                   │ HTTP POST /chat {user_id, message, history, api_key, model}
                   ▼
         Pi-Agent Service (Node.js)
                   │ Agent.prompt(message) + 10 Tools registriert
                   ▼
         pi-agent-core orchestriert LLM + Tools
                   │ Bei Tool-Call z.B. get_training_load
                   ▼
         HTTP GET /api/tools/training-load?user_id=X
                   │ Bearer: INTERNAL_API_TOKEN
                   ▼
         Python Tools API (Flask)
                   │ services/garmin.get_training_load(user_id)
                   ▼
         Supabase DB → ATL/CTL/TSB zurück
                   │ JSON Response
                   ▼ (zurück durch die Chain)
         LLM verwendet Tool-Ergebnis für Antwort
                   │ Finaler Text
                   ▼
         Python Bot → Telegram User
```
