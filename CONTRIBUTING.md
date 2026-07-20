# Contributing to WODpilot

## Development Setup

### Voraussetzungen

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- Git

### Python-Umgebung einrichten

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
```

### Node.js-Umgebung (pi-agent-service) einrichten

```bash
cd pi-agent-service
npm install
```

### Lokale Entwicklung

```bash
# Alle Services starten
docker compose up --build

# Nur einzelne Services neustarten
docker compose up --build web
docker compose up --build pi-agent-service
```

## Projektstruktur

```
Wodpilot/
├── bot/                # Telegram Bot Handler
│   ├── handlers.py     # Post-Registrierungs-Handler (chat, photo, video, commands)
│   └── registration.py # 6-stufiger Registrierungs-Flow (ConversationHandler)
├── db/
│   ├── client.py       # Supabase-Client (Singleton)
│   └── migrations/     # SQL-Migrationen (manuell in Supabase ausführen)
├── memory/
│   ├── working.py      # Letzte 20 Nachrichten (Supabase)
│   ├── semantic.py     # pgvector Semantic Search
│   ├── episodic.py     # Events: PRs, Verletzungen, Achievements
│   └── procedural.py   # Coaching-Stil-Profil
├── pi-agent-service/   # Node.js pi-agent Microservice
│   ├── src/
│   │   ├── server.ts   # Express HTTP Server (:3001)
│   │   ├── agent.ts    # pi-agent Setup, History-Konvertierung
│   │   ├── tools.ts    # 10 Tool-Definitionen (rufen Python API auf)
│   │   └── types.ts    # TypeScript Interfaces
│   └── Dockerfile
├── services/
│   ├── garmin.py       # Garmin Connect API, TSS/ATL/CTL/TSB
│   ├── pi_agent_client.py  # Python HTTP-Client für pi-agent
│   ├── scheduler.py    # APScheduler Jobs (Garmin sync, WOD scrape, Briefings)
│   ├── scraper.py      # BeautifulSoup WOD Scraper
│   └── training_load.py    # TSS/ATL/CTL/TSB Berechnung
├── deploy/nas/         # Synology-Deployment (Compose, Postgres+PostgREST, Doku)
├── tests/              # pytest Tests
├── utils/
│   └── crypto.py       # Fernet AES-128 Verschlüsselung
└── web/
    ├── app.py          # Flask Admin Dashboard + /api/tools/* Routes
    └── templates/      # Jinja2 HTML Templates
```

## Tests ausführen

```bash
# Alle Tests
PYTHONPATH=/usr/local/lib/python3.11/dist-packages pytest tests/ -v

# Einzelne Test-Datei
pytest tests/test_training_load.py -v
```

Aktuelle Test-Coverage:
- `tests/test_crypto.py` – Fernet-Verschlüsselung
- `tests/test_scraper.py` – WOD Scraper (gemockt)
- `tests/test_training_load.py` – ATL/CTL/TSB Berechnungen

## TypeScript (pi-agent-service)

```bash
cd pi-agent-service

# Build
npm run build

# Entwicklung mit Hot-Reload
npm run dev
```

## Branches

| Muster | Zweck |
|--------|-------|
| `main` | Production-Branch, nur via PR |
| `feature/<name>` | Neue Features |
| `fix/<name>` | Bugfixes |
| `claude/<name>` | Automatisierte Änderungen (Claude Code) |

## Pull Request Checklist

- [ ] Alle Tests laufen durch (`pytest tests/ -v`)
- [ ] TypeScript kompiliert (`cd pi-agent-service && npm run build`)
- [ ] Keine neuen Env-Variablen ohne `.env.example`-Eintrag
- [ ] SQL-Migrationen in `db/migrations/` wenn Schema geändert
- [ ] `docker compose up --build` läuft ohne Fehler

## Wichtige Designprinzipien

1. **BYOK** – Kein gemeinsamer API-Key; jeder User bringt seinen eigenen Anthropic-Key
2. **Encryption at Rest** – Garmin-Passwörter und API-Keys werden Fernet-verschlüsselt gespeichert
3. **Stateless pi-agent** – Conversation History wird vom Python-Bot verwaltet und per Request übergeben
4. **Rate Limiting** – `MAX_API_CALLS_PER_DAY` verhindert Kostenexplosion bei einzelnen Nutzern
5. **DSGVO** – Vollständige Datenlöschung via `/delete`; Einwilligung bei Registrierung

## Neue WOD-Quellen hinzufügen

WOD-Quellen werden in der Supabase-Tabelle `config` als JSON gespeichert (Key: `wod_sources`).
Format: `[{"url": "https://...", "name": "Box Name", "selector": "css-selector"}]`

Der Scraper in `services/scraper.py` verwendet BeautifulSoup mit CSS-Selektoren und einem Fallback-Mechanismus.
