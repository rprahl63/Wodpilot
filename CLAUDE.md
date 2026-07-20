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

### Nach jeder Entwicklung deployen

Änderungen gelten erst als fertig, wenn sie auf dem NAS laufen. Der Ablauf steht
vollständig in `deploy/nas/README.md` unter „Update auf eine neue Version".
Kurzfassung – **Reihenfolge ist wichtig, erst Schema, dann Container**:

```bash
ssh nas
cd /volume1/docker/wodpilot
git pull

cd deploy/nas
docker compose exec -T db psql -U wodpilot -d wodpilot < ../../db/migrations/<neue>.sql
docker compose build
docker compose up -d
docker compose logs -f bot
```

Neue Migrations laufen **nicht** automatisch: `initdb/` greift nur bei leerer
Datenbank. Bei bestehender DB immer von Hand per `psql` einspielen, sonst
trifft neuer Code auf altes Schema.

`docker compose build` ist zugleich der TypeScript-Check (das pi-agent-Dockerfile
ruft `npm run build`), da auf dem Entwicklungs-Mac kein Node installiert ist.

### Zugang

Der SSH-Zugang liegt als Host `nas` in `~/.ssh/config`; der Key kommt aus dem
Bitwarden-SSH-Agent und braucht dort eine interaktive Freigabe. Schlägt die
Authentifizierung fehl, ist in der Regel Bitwarden gesperrt – dann den Nutzer
bitten, es zu entsperren, statt nach Passwörtern zu fragen.

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
