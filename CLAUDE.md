# WODpilot – Arbeitsanweisungen

## Deployment-Ziel: Synology NAS

Dieses Projekt läuft **ausschließlich auf der Synology DS218+ im LAN**
(`nasrpsave`, 192.168.2.50). Der frühere Hetzner-VPS-Pfad (Terraform, Traefik,
Let's Encrypt, GHCR-Images, GitHub-Actions-Deploy) ist entfernt und darf nicht
wieder eingeführt werden.

Konkret heißt das:

- Es gibt **keine öffentliche Domain und keinen eingehenden Port**. Der Bot
  arbeitet per Long Polling, das Dashboard ist nur über NetBird erreichbar.
- Images werden **lokal auf dem NAS gebaut**, nicht aus einer Registry gezogen.
- Statt Supabase Cloud laufen **Postgres + PostgREST lokal** (siehe
  `deploy/nas/README.md`).

### Zugang zum NAS

**Nicht** `ssh nas` direkt benutzen – die Key-Anmeldung scheitert daran, dass der
Bitwarden-Agent das Signieren ohne interaktive Freigabe verweigert
(`agent refused operation`). Stattdessen den Helfer aus dem `synology-nas`-Skill
verwenden, der auf Passwort-Auth zurückfällt:

```bash
bash /Users/reneprahl/Documents/nas/.claude/skills/synology-nas/scripts/nas_run.sh "BEFEHL"
```

Zwei Fallstricke, die Zeit kosten, wenn man sie nicht kennt:

- Der Helfer tippt den Befehl in eine interaktive Shell und **verdoppelt dabei
  gelegentlich Zeichen** (`dockker`, `echho`). Bei längeren Befehlen führt das zu
  falschen Ergebnissen, die wie echte Befunde aussehen. Für alles Wichtige lieber
  `ssh -tt host BEFEHL` nicht-interaktiv ausführen und die Passwort-Prompts per
  `expect` beantworten.
- `sudo` setzt den PATH zurück: Docker immer als `/usr/local/bin/docker`
  aufrufen, sonst `command not found`. Docker braucht auf diesem NAS `sudo`.

### Deployment

Auf dem NAS ist **kein Git installiert**, und `/volume1/docker/wodpilot` ist
*kein* Repo, sondern ein einfaches Verzeichnis. `git pull` funktioniert dort
nicht. Das Repo ist öffentlich, deshalb lädt sich das NAS den Stand direkt als
Tarball:

```bash
# 1. Branch auf dem NAS holen (BRANCH anpassen)
rm -rf /tmp/wp && mkdir -p /tmp/wp
curl -fsSL https://codeload.github.com/rprahl63/Wodpilot/tar.gz/refs/heads/BRANCH \
  | tar xz -C /tmp/wp --strip-components=1

# 2. Ueber die Installation kopieren.
#    Das Tarball enthaelt weder deploy/nas/.env noch deploy/nas/data,
#    beides bleibt dadurch unangetastet. sudo ist noetig, weil die Dateien
#    einem anderen Benutzer gehoeren.
sudo cp -a /tmp/wp/. /volume1/docker/wodpilot/

# 3. Migrations von Hand einspielen – initdb/ greift nur bei leerer DB!
sudo /usr/local/bin/docker exec -i wodpilot-db psql -U wodpilot -d wodpilot \
  < /volume1/docker/wodpilot/db/migrations/<neue>.sql

# 4. Bauen und starten
cd /volume1/docker/wodpilot/deploy/nas
sudo /usr/local/bin/docker compose build
sudo /usr/local/bin/docker compose up -d

# 5. Nach JEDER Migration: PostgREST cached das Schema und kennt neue
#    Tabellen sonst nicht – die App liefe gegen 404.
sudo /usr/local/bin/docker restart wodpilot-postgrest
sudo /usr/local/bin/docker logs wodpilot-postgrest --tail 3   # "Schema cache loaded N Relations"

sudo /usr/local/bin/docker compose logs -f bot
```

Zwei Dinge, die nach einer Migration erfahrungsgemäß schiefgehen:

- **PostgREST-Schemacache** (siehe Schritt 5). Die Relationszahl im Log muss um
  die Zahl der neuen Tabellen gestiegen sein.
- **Rechte für `service_role`.** `initdb/40-grants.sql` setzt
  `ALTER DEFAULT PRIVILEGES`, das aber nur für Objekte gilt, die von *derselben
  Rolle* angelegt wurden. Migrations deshalb immer als `-U wodpilot` einspielen,
  sonst fehlen die Grants. Prüfen mit `\dp <tabelle>` – dort muss
  `service_role=arwdDxt` stehen, bei den `_id_seq`-Sequenzen `service_role=rwU`.

### Wenn der web-Container nicht startet

`bind: cannot assign requested address` heißt: Die NetBird-IP hat sich geändert.
Aktuelle IP holen und `BIND_IP` in `deploy/nas/.env` anpassen, dann
`docker compose up -d`. `DASHBOARD_BASE_URL` folgt automatisch, weil es im
Compose aus `BIND_IP` abgeleitet wird.

```bash
sudo /usr/local/bin/docker exec netbird netbird status | grep "NetBird IP"
```

**Reihenfolge ist wichtig: erst Schema, dann Container.** Der Bot fragt schon
bei der ersten Chatnachricht `training_plans` ab.

Niemals `rsync --delete` oder `cp` mit `--delete`-Semantik auf das Zielverzeichnis
loslassen: Unter `deploy/nas/data/db` liegt die **laufende Postgres-Datenbank**,
unter `deploy/nas/.env` die Secrets. Beides ist nicht im Repo.

`docker compose build` ist zugleich der TypeScript-Check (das pi-agent-Dockerfile
ruft `npm run build`), da auf dem Entwicklungs-Mac kein Node installiert ist.

## Weitere NAS-Informationen

Kontext zum NAS, der **nicht** in dieses Repo gehört – Backup-Konzept,
Container-Landschaft, Home-Assistant-Konfiguration – liegt lokal unter:

```
/Users/reneprahl/Documents/nas
```

Dort nachsehen, wenn es um Backups, andere Container auf dem NAS oder das
Zusammenspiel mit Home Assistant, Immich und Vaultwarden geht. Besonders
relevant: `BACKUP_KONZEPT.md` (nächtliches `nas_backup_prep.sh` um 02:30 sichert
auch WODpilots `.env` samt `ENCRYPTION_KEY` – ohne den ist jeder DB-Dump wertlos).

**Keine Zugangsdaten, Keys, Tokens oder IP-Geheimnisse in dieses Repo committen.**
Secrets leben in `deploy/nas/.env` (chmod 600, nicht versioniert) und im
Bitwarden. `.env.example` enthält nur Platzhalter.

## Sonstiges

- Nutzertexte sind **deutsch**, Code-Kommentare englisch.
- Tests: `pytest tests/` – müssen vor jedem Deploy grün sein.
- Architekturüberblick: `docs/ARCHITECTURE.md`.
