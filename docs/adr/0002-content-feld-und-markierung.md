# ADR 0002: LLM-Text ersetzt `content`, Markierung in Text und Tag

- **Status:** angenommen
- **Datum:** 2026-10-19

## Kontext

`paperplus.py` soll das LLM-Ergebnis in Paperless hinterlegen (ADR 0001). Auf das Feld
`content` bauen Volltextsuche, automatische Zuordnung, Klassifikator und die KI-Vorschläge von
Paperless 3.x auf. Die LLM-Antwort ist HTML (Struktur), HTML-Tags würden aber in der Oberfläche
roh erscheinen und den Suchindex verschmutzen.

Paperless kann `content` jederzeit durch eine neue Tesseract-OCR überschreiben
(„Neu verarbeiten“). Das soll später erkennbar sein.

## Entscheidung

- **Reiner Text aus der LLM-Antwort ersetzt den Tesseract-Text im Feld `content`.**
  Absätze, `<br/>`, Listeneinträge und Tabellenzeilen werden zu Zeilenumbrüchen, Tabellenzellen
  durch ` | ` getrennt, Leerzeilen entfernt, Bildbeschreibungen weggelassen (`llm.html_to_text`).
- **Markierung doppelt:** Am Ende von `content` steht die Zeile `llm-angereichert (<modell>)`,
  zusätzlich bekommt das Dokument den Tag `llm-angereichert` (ohne automatische Zuordnung).
  Tag ohne Markierung im Text ⇒ `content` wurde vermutlich durch Tesseract überschrieben.
- Das HTML wird nur lokal in `ausgabe/<doc-id>_<titel>/<modell>.html` abgelegt, der
  ursprüngliche Tesseract-Text als `paperless_content.txt` gesichert (nie überschrieben).
- Dokumente mit Tag werden standardmäßig übersprungen (`--force` erzwingt), `--no-write`
  verarbeitet nur lokal.

## Konsequenzen

- Suche und Einsortierung in Paperless arbeiten mit dem deutlich besseren Text.
- Die Dokumentstruktur (HTML) ist in Paperless selbst nicht sichtbar. Ein `longtext`-Custom-Field
  dafür wurde erwogen, aber vorerst nicht umgesetzt.
- Die Markierungszeile ist Teil des Volltexts und erscheint in der Paperless-Oberfläche.
- Der genaue Suchausdruck zum Finden „degradierter“ Dokumente ist noch an der Paperless-Suche
  zu prüfen.

## Nachtrag (2026-10-19)

Die lokale Sicherung des Tesseract-Textes (`paperless_content.txt`) entfällt. Paperless speichert
Änderungen an Dokumenten einschließlich `content` selbst im Änderungsverlauf; eine zweite Kopie
ist überflüssig. Lokal bleiben nur Originaldatei und HTML-Antwort.
