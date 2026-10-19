# ADR 0001: Zwei unabhängige Teile – Anreichern und Benchmarken

- **Status:** angenommen
- **Datum:** 2026-10-19

## Kontext

Paperless-ngx (TrueNAS-App, Version 3.3.1, Server ohne Grafikkarte) erkennt Text mit Tesseract.
Bei Handyfotos ist das Ergebnis sehr schlecht (Wortgenauigkeit 0–48 % auf den Referenzdokumenten).
Vision-LLMs lesen die Fotos deutlich besser, unterscheiden sich aber stark in Qualität und Tempo.

Rahmenbedingungen:

- Die LLMs laufen lokal auf einem MacBook Pro M3 (36 GB RAM) über LM Studio; die Dokumente
  verlassen das Heimnetz nicht. Der Mac ist nicht dauerhaft an, wenige Dokumente, Verarbeitung
  „ab und zu“ genügt.
- Ein erster Vergleich (chandra-ocr-2 gegen Tesseract) brauchte Referenzdokumente mit
  manuell korrigiertem Text (Ground Truth).
- Anfangs hat `paperplus.py` nach jedem Lauf automatisch bewertet und damit zwei Aufgaben vermischt.

## Entscheidung

Die Anwendung besteht aus zwei voneinander unabhängigen Teilen:

1. **`paperplus.py` – Anreichern.** Holt Dokumente aus Paperless, lässt sie vom eingestellten
   LLM (`LMSTUDIO_MODEL`) lesen und hinterlegt das Ergebnis in Paperless. Bewertet nichts.
2. **`evaluate.py` – Benchmarken.** Bewertet ein lokales LLM anhand der Referenzdokumente in
   `referenz/<doc-id>_<titel>/` (`original.<ext>` + `ground_truth.html`). Greift nicht auf
   Paperless zu.

Weitere Festlegungen:

- **Läuft auf dem Mac**, wird bei Bedarf gestartet (`run.sh`); auf dem TrueNAS wird nichts
  zusätzlich installiert. Kommunikation mit Paperless nur über die REST-API.
- **LM Studio** als Laufzeit für lokale Modelle (OpenAI-kompatible API, Steuerung per `lms`):
  Server starten, Modell laden, nach dem Lauf wieder entladen.
- **HTML als Ergebnisformat**, angelehnt an das native Format von chandra-ocr-2, damit die
  Dokumentstruktur (Überschriften, Absätze, Tabellen) erhalten bleibt.
- **Metriken** im Benchmark: Zeichen (1−CER), Wörter (1−WER) auf dem aus dem HTML extrahierten
  Text sowie Ähnlichkeit der HTML-Struktur; der Tesseract-Text dient als Basislinie.
- **Python mit Standardbibliothek**, Bildaufbereitung mit macOS-Bordmitteln (`sips`, `qlmanage`),
  optional `pdftoppm` für mehrseitige PDFs.
- **Eingestelltes Modell:** chandra-ocr-2 (Benchmark: 96,5–100 % Zeichen, 85–100 % Wörter).

## Konsequenzen

- Modelle lassen sich vergleichen, ohne Paperless zu berühren; das Anreichern bleibt schlank.
- Das Ergebnis des Benchmarks fließt nur über die Konfiguration (`LMSTUDIO_MODEL`) in das
  Anreichern ein.
- Beide Teile brauchen Zugriff auf LM Studio und die Bildaufbereitung. Ob dieser Code geteilt
  oder dupliziert wird, ist noch zu entscheiden.
- **Noch nicht umgesetzt:** `evaluate.py` ruft das LLM noch nicht selbst auf, sondern vergleicht
  Ausgaben, die `paperplus.py` in `ausgabe/` abgelegt hat. `paperplus.py` schreibt noch nicht nach
  Paperless; das Zielfeld ist noch festzulegen (eigenes ADR).
- Die Referenzdokumente enthalten persönliche Daten und werden trotzdem eingecheckt
  (Entscheidung des Users). Das Repository darf daher nicht öffentlich werden.
