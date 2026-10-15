# paperplusLLM

Holt einzelne Dokumente von Paperless-ngx, lässt den Inhalt der Fotos/Scans von mehreren LLMs
extrahieren und legt pro LLM eine Ergebnisdatei neben das Dokument. Paperless wird nur gelesen.

> **Status:** Konzeptphase, noch keine lauffähige Anwendung.

## Voraussetzungen

- Paperless-ngx mit API-Token
- Mac mit LM Studio (lokale Vision-Modelle, API unter `http://localhost:1234/v1`)
- optional Claude-Code-CLI (`claude -p`)

## Ausgabe (Vorschlag)

```
ausgabe/<doc-id>_<titel>/
├── original.<ext>
├── tesseract.txt
└── <llm-name>.md
```

## Offen

Sprache/Form, Modellauswahl, Dokumentauswahl, Ausgabeformat, mehrseitige PDFs.
