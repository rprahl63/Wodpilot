---
name: wodpilot-issues
description: Issues aus dem WODpilot-Backlog abrufen und abarbeiten – Bug-Reports und Feature-Wünsche, die Athleten im Telegram-Chat gemeldet haben. Nutze diesen Skill bei "Issues abarbeiten", "was liegt an", "Backlog", "Issue #12", "gibt es neue Meldungen" oder wenn nach dem Stand einer Meldung gefragt wird.
---

# WODpilot-Issues abarbeiten

Athleten melden Bugs und Wünsche im Telegram-Chat; der Coach legt sie über sein
`create_issue`-Tool in der Tabelle `issues` ab. Der MCP-Server `wodpilot-issues`
(Container auf dem NAS, nur über NetBird erreichbar) macht sie hier verfügbar.

**Der Melder bekommt automatisch eine Telegram-Nachricht, sobald ein Issue auf
`done` oder `rejected` geht.** Alles, was du in `resolution` bzw. `reason`
schreibst, geht wörtlich an einen echten Menschen. Das prägt den ganzen Workflow.

## Statusmodell

| Status | Bedeutung | Wer setzt ihn |
|---|---|---|
| `open` | Gemeldet, niemand arbeitet daran | der Coach beim Anlegen |
| `in_progress` | Von einer Session übernommen | `claim_issue` |
| `done` | Umgesetzt **und auf dem NAS deployed** | `resolve_issue` |
| `rejected` | Wird nicht umgesetzt | `reject_issue` |

`done` heißt deployed, nicht gemergt. Der Athlet bekommt in dem Moment die
Nachricht und schaut nach – findet er die Änderung nicht, ist die Meldung
schlimmer als keine. Ist der Code fertig, aber noch nicht auf dem NAS, bleibt das
Issue auf `in_progress`.

## Ablauf

1. **Backlog holen:** `list_issues(status="open")`. Für den Gesamtüberblick
   `status="open,in_progress"`. Die Liste ist nach Priorität sortiert.
2. **Issue lesen:** `get_issue(id)` – der `body` enthält die Schilderung in den
   Worten des Athleten. Bei Unklarheiten nicht raten: den Nutzer fragen, ob er
   beim Melder nachhaken soll.
3. **Übernehmen:** `claim_issue(id)`. Gibt es `None` zurück, ist das Issue nicht
   mehr `open` – dann arbeitet jemand anders daran; ein anderes wählen.
4. **Umsetzen:** Branch anlegen, Änderung bauen. Konventionen stehen in
   `CLAUDE.md`: Nutzertexte deutsch, Code-Kommentare englisch.
5. **Prüfen:** `pytest tests/` muss grün sein. Betrifft die Änderung
   `pi-agent-service/`, ist `docker compose build` auf dem NAS zugleich der
   TypeScript-Check – auf dem Entwicklungs-Mac ist kein Node installiert.
6. **Deployen:** nach der Anleitung in `CLAUDE.md` (Tarball aufs NAS, Migrations
   von Hand, PostgREST nach jeder Migration neu starten, dann `compose up -d`).
7. **Abschließen:** `resolve_issue(id, resolution="…")`.

## Text für den Melder

`resolution` und `reason` gehen ohne Markup über die Telegram-Bot-API raus.

- Deutsch, ein bis drei Sätze.
- Beschreibe, was der Athlet **jetzt anders erlebt**, nicht was im Code passiert
  ist. Nicht: „Race Condition in `claim_planning` behoben." Sondern: „Der
  Wochenplan wird jetzt nur noch einmal erstellt, auch wenn du sonntags
  gleichzeitig antwortest."
- Kein Markdown, keine Backticks, keine Dateipfade, keine Commit-Hashes.
- Keine Terminversprechen.

## Wann `reject_issue`

- **Duplikat** – die Nummer des Originals nennen.
- **Trainingswunsch statt Produktfehler** – auf `/dashboard` und die
  Trainingspräferenzen verweisen.
- **Außerhalb des Produktziels** – kurz und respektvoll begründen; der Melder
  hat sich die Mühe gemacht.

Nie ohne Begründung ablehnen und nie stillschweigend liegen lassen.

## Sonderfälle

- **Fix funktioniert doch nicht:** `reopen_issue(id)` setzt zurück auf `open` und
  löscht die Resolution. Der Melder wird dabei *nicht* benachrichtigt.
- **Issue braucht eine DB-Migration:** die beiden Fallstricke aus `CLAUDE.md`
  beachten – PostgREST-Schemacache neu laden und Migrations als `-U wodpilot`
  einspielen, sonst fehlen die Grants für `service_role`.
- **MCP nicht erreichbar:** `WODPILOT_MCP_URL` und `WODPILOT_MCP_TOKEN` müssen in
  der Shell gesetzt sein (siehe `.mcp.json`), und der Mac muss im NetBird-Netz
  sein. Notfalls zeigt das Admin-Dashboard unter `/issues` dieselbe Liste.
