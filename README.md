# paperplusLLM

Lässt Dokumente aus Paperless-ngx von einem lokalen Vision-LLM (LM Studio) lesen, um die
schwache Tesseract-Texterkennung zu ersetzen. Zwei unabhängige Teile, gemeinsamer Code in `llm.py`:

| Teil | Zweck |
|---|---|
| `paperplus.py` (`run.sh`) | **Anreichern:** Dokumente aus Paperless mit dem eingestellten LLM lesen, Text in Paperless ersetzen |
| `evaluate.py` | **Benchmarken:** ein LLM anhand der Referenzdokumente in `referenz/` bewerten |

Architekturentscheidungen: [`docs/adr/`](docs/adr/)

## Voraussetzungen

- Python 3.9+ (nur Standardbibliothek), macOS (`sips`, `qlmanage`)
- Paperless-ngx mit API-Token (Schreibrechte für Dokumente und Tags)
- LM Studio mit einem Vision-Modell (`lms get <modell>`), aktuell `chandra-ocr-2`
- optional `brew install poppler` für mehrseitige PDFs (sonst nur Seite 1)

## Einrichtung

```bash
cp .env.example .env   # PAPERLESS_TOKEN und LMSTUDIO_MODEL eintragen
```

## Anreichern – `paperplus.py`

```bash
./run.sh                      # neuestes Dokument
./run.sh --latest 3           # die drei neuesten
./run.sh 1234 1240            # bestimmte IDs
./run.sh --no-write 1234      # nur lokal, Paperless nicht verändern
./run.sh --force 1234         # bereits angereicherte Dokumente erneut verarbeiten
./run.sh --skip-llm 1234      # nur aus Paperless laden, ohne LLM
```

Weitere Optionen: `./run.sh --help`

In Paperless:

- Feld **`content`** wird durch den reinen Text der LLM-Antwort ersetzt (Zeilen und
  Tabellenzeilen als Zeilenumbrüche, Zellen durch ` | ` getrennt). Letzte Zeile:
  `llm-angereichert (<modell>)`.
- Tag **`llm-angereichert`** wird gesetzt; solche Dokumente werden beim nächsten Lauf übersprungen.
- Frühere Fassungen von `content` stehen im Änderungsverlauf von Paperless.
- Tag vorhanden, aber Markierung fehlt im Text ⇒ `content` wurde vermutlich durch eine neue
  Tesseract-OCR überschrieben.

Lokal:

```
ausgabe/<doc-id>_<titel>/
├── original.<ext>
└── <modell>.html                # Antwort des LLMs (HTML mit Struktur)
```

## Benchmarken – `evaluate.py`

```
referenz/<doc-id>_<titel>/
├── original.<ext>
├── ground_truth.html            # vom Menschen korrigierte Fassung
└── tesseract.txt                # optional, Basislinie
```

```bash
python3 evaluate.py                   # eingestelltes Modell auf alle Referenzen
python3 evaluate.py 220 210           # bestimmte IDs
python3 evaluate.py --model <key>     # anderes Modell
python3 evaluate.py --score-only      # nur vorhandene Antworten neu bewerten
```

Antworten in `benchmark/<doc-id>_<titel>/<modell>.html`, Werte in Konsole und
`benchmark/bewertung.csv`. Antworten mehrerer Modelle werden nebeneinander bewertet.

| Metrik | Bedeutung |
|---|---|
| Zeichen | 1 − Zeichenfehlerrate (CER) |
| Wörter | 1 − Wortfehlerrate (WER) |
| Struktur | Ähnlichkeit der HTML-Struktur (Überschriften, Absätze, Tabellen, Listen) |

Verglichen wird der aus dem HTML extrahierte Text; Bildbeschreibungen (`alt`) zählen nicht mit.
