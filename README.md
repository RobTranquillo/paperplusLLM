# paperplusLLM

Holt einzelne Dokumente von Paperless-ngx, lässt den Inhalt der Fotos/Scans von LLMs
extrahieren und legt pro LLM eine Ergebnisdatei neben das Dokument. Paperless wird nur gelesen.

## Voraussetzungen

- Python 3.9+ (nur Standardbibliothek), macOS (`sips`, `qlmanage`)
- Paperless-ngx mit API-Token
- LM Studio mit einem Vision-Modell (`lms get <modell>`)
- optional `brew install poppler` für mehrseitige PDFs (sonst nur Seite 1)

## Einrichtung

```bash
cp .env.example .env   # PAPERLESS_TOKEN und LMSTUDIO_MODEL eintragen
```

## Aufruf

```bash
./run.sh                      # neuestes Dokument
./run.sh --latest 3           # die drei neuesten
./run.sh 1234 1240            # bestimmte IDs
./run.sh --skip-llm 1234      # nur aus Paperless laden, ohne LLM
./run.sh --model qwen/qwen3-vl-8b --with-ocr 1234
```

Weitere Optionen: `./run.sh --help`

## Ausgabe

```
ausgabe/<doc-id>_<titel>/
├── original.<ext>
├── paperless_content.txt        # vorhandener Paperless-Text (Feld "content")
├── <modell>.html                # Antwort des LLMs (HTML mit Struktur)
└── <modell>_mit-ocr.html        # mit --with-ocr
```

## Referenzen und Bewertung

Korrigierte Fassungen dienen als Ground Truth (nicht im Git, enthalten persönliche Daten):

```
referenz/<doc-id>_<titel>/
├── original.<ext>
└── ground_truth.html
```

Nach jedem Lauf werden die Ergebnisse automatisch gegen vorhandene Referenzen bewertet,
manuell mit `python3 evaluate.py [ids]`. Ergebnis zusätzlich in `ausgabe/bewertung.csv`.

| Metrik | Bedeutung |
|---|---|
| Zeichen | 1 − Zeichenfehlerrate (CER) |
| Wörter | 1 − Wortfehlerrate (WER) |
| Struktur | Ähnlichkeit der HTML-Struktur (Überschriften, Absätze, Tabellen, Listen) |

Verglichen wird der aus dem HTML extrahierte Text; Bildbeschreibungen (`alt`) zählen nicht mit.
Der Tesseract-Text aus Paperless wird als Vergleichsbasis mitbewertet.
