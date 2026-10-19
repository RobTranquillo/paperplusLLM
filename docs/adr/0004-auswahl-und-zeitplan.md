# ADR 0004: Dokumentauswahl und regelmäßiger Lauf

- **Status:** angenommen
- **Datum:** 2026-10-19

## Kontext

`paperplus.py` soll auf dem MacBook regelmäßig laufen und neue Dokumente in Paperless automatisch
anreichern. Bestand: 209 Dokumente, davon 139 Fotos (JPEG/PNG), 54 PDFs, 15 Text/CSV.
Digital erzeugte PDFs haben bereits korrekten Text; ein LLM kann ihn nicht verbessern. Einige
Fotos liegen aber als PDF in Paperless und lassen sich am Dateityp nicht erkennen.

## Entscheidung

**Auswahl** (ohne angegebene IDs) – ein Dokument wird angereichert, wenn

1. es ein **Foto** ist (MIME-Typ `image/*`) und den Tag **`llm-angereichert` nicht** hat, **oder**
2. es den Tag **`llm-ausstehend`** hat – unabhängig vom Dateityp und auch, wenn es bereits
   `llm-angereichert` trägt (bewusste Anforderung durch den User, z. B. als PDF abgelegte Fotos).

Nach erfolgreicher Anreicherung wird `llm-angereichert` gesetzt und `llm-ausstehend` entfernt.
PDFs werden vorerst nur über `llm-ausstehend` verarbeitet; Text/CSV nie automatisch.

**Abarbeitung:** neueste zuerst, jedes Dokument einzeln (holen → LLM → zurückschreiben). Der
Altbestand wird in einem Durchgang abgearbeitet; ein Abbruch ist unkritisch, da der nächste Lauf
die noch nicht markierten Dokumente erneut auswählt. Tags werden direkt vor dem Schreiben frisch
gelesen, damit zwischenzeitliche Änderungen in Paperless nicht verloren gehen.

**Zeitplan:** launchd-LaunchAgent `local.paperplusllm` (`install-launchd.sh`), alle 6 Stunden und
beim Anmelden, startet `run.sh --auto`. Im Modus `--auto`:

- nur am Netzteil (`pmset -g batt`), sonst still beenden,
- Paperless nicht erreichbar (unterwegs) ⇒ still beenden ohne Fehler,
- LM Studio wird nur gestartet, wenn es etwas zu tun gibt, und danach entladen,
- macOS-Mitteilung am Ende, wenn Dokumente verarbeitet wurden oder Fehler auftraten,
- Ausgabe nach `~/Library/Logs/paperplusLLM.log`.

## Konsequenzen

- Neue Fotos werden ohne Einrichtung in Paperless erkannt; PDFs mit Foto-Inhalt markiert der User
  per Tag. Ein Paperless-Workflow ist nicht nötig.
- Der erste Lauf verarbeitet rund 160 Dokumente (ca. 2–3 Stunden).
- Dauerhaft fehlschlagende Dokumente werden bei jedem Lauf erneut versucht (kein Fehler-Tag).
- Läuft nur, wenn der Mac an, angemeldet und am Netzteil ist; verpasste Läufe holt launchd nach
  dem Aufwachen einmal nach.
