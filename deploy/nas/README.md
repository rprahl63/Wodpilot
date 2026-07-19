# WODpilot auf der Synology DS218+

Deployment ohne Hetzner, ohne Domain, ohne öffentlichen Port. Dashboard und Chat
sind ausschließlich über NetBird erreichbar, der Telegram-Bot arbeitet per Long
Polling und braucht daher keinen eingehenden Traffic.

## Was hier anders ist als im Upstream-Repo

| Upstream (VPS) | Hier (NAS) |
|---|---|
| Traefik + Let's Encrypt + `DOMAIN` | entfällt — kein öffentlicher Entrypoint |
| Supabase Cloud | Postgres + PostgREST lokal |
| Images von ghcr.io | lokal gebaut |
| `PYTHON_API_URL=http://web:5000` | `http://web:8080` — **Upstream-Bug**, siehe unten |
| gunicorn `--workers 2` | `--workers 1 --threads 4` (RAM) |

### Der Upstream-Bug

`docker-compose.yml` und `pi-agent-service/src/tools.ts:4` zeigen beide auf Port
5000, aber die Web-App lauscht auf 8080 (`config.py:34`, `Dockerfile.web`). Damit
laufen im Upstream **alle Agent-Tool-Aufrufe** ins Leere: Der Bot antwortet, hat
aber keinen Zugriff auf Trainingsdaten, WODs, PRs oder Memory. Hier korrigiert.
Für einen Upstream-Fix müsste der Default in `tools.ts` mitgeändert werden.

## Warum Postgres + PostgREST statt Supabase

Der Code nutzt von Supabase nur Tabellen-CRUD und zwei RPCs — kein Auth, kein
Storage, kein Realtime (`grep` über `db/migrations/` findet keine RLS-Policies,
kein `auth.`-Schema). `supabase-py` spricht ohnehin PostgREST.

Zwei Details machen das kompatibel:

1. Die Library baut ihre URLs als `{SUPABASE_URL}/rest/v1/…`, PostgREST serviert
   aber auf `/`. Der nginx in `rest-shim.conf` schneidet das Präfix ab.
2. `SUPABASE_SERVICE_KEY` muss ein **echtes JWT** sein — die Library prüft die
   Form per Regex, PostgREST prüft die Signatur gegen `JWT_SECRET`.
   `gen-secrets.sh` erzeugt beides zusammenpassend.

Verifiziert mit `verify.py`: Insert, Select, Update, Delete, `not_.is_`-Filter und
die pgvector-RPC mit 1536-dim Embeddings laufen unverändert. Ohne JWT: HTTP 401.

## Setup

```bash
# 1. Secrets erzeugen und .env füllen
cd deploy/nas
bash gen-secrets.sh > .env.generated
cp .env.example .env
# .env.generated in .env übernehmen, dann TELEGRAM_TOKEN,
# ADMIN_TELEGRAM_ID und WEB_ADMIN_PASSWORD eintragen.
chmod 600 .env

# 2. Bind-Mount-Verzeichnisse anlegen
#    Synologys Docker legt sie NICHT automatisch an und bricht sonst ab.
mkdir -p data/db data/bot

# 3. Starten
docker compose up -d
```

Die Migrations laufen automatisch beim ersten Start über
`/docker-entrypoint-initdb.d` — **nur solange `data/db` leer ist**. Spätere
Schema-Änderungen müssen von Hand per `psql` eingespielt werden.

## Zugriff

Dashboard und Chat: `http://<netbird-ip>:8080` — nur aus dem NetBird-Netz.

Die IP kommt aus `BIND_IP` in der `.env`. Sie ist an das `wt0`-Interface des
NetBird-Containers gebunden, der im Host-Netzwerk läuft. Prüfen mit:

```bash
docker exec netbird netbird status | grep "NetBird IP"
```

**Wichtig:** Ändert sich diese IP, startet der `web`-Container nicht mehr
(Docker kann den Port nicht binden). Dann `BIND_IP` in der `.env` anpassen und
`docker compose up -d web`.

## Betrieb

```bash
docker compose logs -f bot          # Bot-Logs
docker compose ps                   # Status
docker compose restart web          # Neustart nach .env-Änderung
docker stats --no-stream            # RAM-Verbrauch prüfen
```

### RAM

Die DS218+ hat 6 GB und lief schon vor diesem Stack im Swap. Die `mem_limit`-
Werte im Compose sind Obergrenzen, damit ein Ausreißer hier nicht Home Assistant
oder Immich mitreißt. Summe der Limits: ~1,5 GB, realer Verbrauch deutlich
darunter.

Wird es eng, ist ein 8-GB-DDR3L-SODIMM (1866 MHz, 1.35 V) anstelle des jetzigen
4-GB-Riegels der wirksamste Hebel — offiziell nicht unterstützt (Synology nennt
6 GB als Maximum, Intel für den J3355 8 GB), in der Praxis für die DS218+ aber
breit als funktionierend berichtet. Reversibel.

## LLM-Zugriff über Requesty

Chat-Modelle *und* Embeddings laufen über den Requesty-Router statt direkt gegen
Anthropic bzw. OpenAI. Damit hängt an einem einzigen Key beides, und das Modell
ist pro Nutzer im Dashboard wählbar.

`pi-ai` kennt Requesty nicht, aber ein `Model` ist ein reines Datenobjekt mit
`baseUrl`, und `Provider` ist ein offener String-Typ — `requesty.ts` baut daher
ein Modell mit `api: "openai-completions"` zusammen, ohne die Library zu forken.
Requesty rechnet Preise pro Token, `pi-ai` pro Million: der Faktor 1e6 steckt in
`perMillion()`.

Die Modell-Auswahl filtert auf `supports_tool_calling`. Ohne Tools hat der Coach
keinen Zugriff auf Trainingsdaten und erzählt nur plausibel klingenden Unsinn.

**Embeddings**: `openai/text-embedding-3-large`, über den `dimensions`-Parameter
auf 1536 gestutzt, damit die bestehende `vector(1536)`-Spalte bleibt. Das kleine
`3-small` reichte nicht: bei deutschen Fragen gegen englisch gespeicherte
Memories landete regelmäßig der falsche Treffer oben.

Ist kein Key verfügbar, wird `NULL` gespeichert und die Suche fällt auf
Textsuche zurück — **kein Null-Vektor**. Gegen einen solchen ist die
Kosinus-Distanz NaN, die Treffer wären dann nicht leer, sondern willkürlich
sortiert.

## Backup

Auf diesem NAS erledigt das `/volume1/docker/scripts/nas_backup_prep.sh`
(nächtlich 02:30 via `/etc/crontab`) mit: `pg_dump` nach `_dbdumps/`
(7 Tage) und ins verschlüsselte OneDrive-Set inklusive `.env` und
Garmin-Token-Cache.

Zwei Fallstricke, die dort bereits behandelt sind:

- Das Glob für Compose/`.env` greift nur **eine** Ebene tief. WODpilot liegt
  unter `docker/wodpilot/deploy/nas/` und braucht deshalb einen eigenen Zweig —
  sonst fehlt ausgerechnet der `ENCRYPTION_KEY` im Backup, und der Dump ist
  wertlos.
- `docker exec` beim Dump **ohne `-t`**: ein TTY wandelt LF in CRLF und
  beschädigt den durchgereichten SQL-Stream.

Standalone, ohne dieses Skript:

```bash
docker compose exec -T db pg_dump -U wodpilot wodpilot | gzip > wodpilot-$(date +%F).sql.gz
cp .env wodpilot-env-$(date +%F).bak   # ENCRYPTION_KEY!
```

## Garmin

Der Token-Cache unter `data/bot/garmin_tokens/<user_id>/` ist nicht optional.
Ein voller SSO-Login bei jedem Sync — so das Upstream-Verhalten — führt
zuverlässig zu HTTP 429. Mit Tokenstore wird der Login-Endpunkt nach dem ersten
Mal gar nicht mehr angefasst.

`garminconnect` probiert fünf Login-Strategien der Reihe nach; 429-Warnungen für
die Mobile-Varianten sind daher nicht zwingend fatal, solange eine der
Portal-Strategien durchkommt. `return_on_mfa=True` verschleiert genau das und
lässt jeden Fehler wie „MFA erforderlich" aussehen — deshalb nicht gesetzt.
