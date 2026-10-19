# ADR 0003: Gemeinsames Hilfsmodul `llm.py`

- **Status:** angenommen (ergänzt ADR 0001)
- **Datum:** 2026-10-19

## Kontext

ADR 0001 trennt Anreichern (`paperplus.py`) und Benchmarken (`evaluate.py`). Offen war, wie beide
an LM Studio und die Bildaufbereitung kommen. Bisher rief `evaluate.py` das LLM gar nicht selbst
auf, sondern bewertete Ausgaben von `paperplus.py` aus `ausgabe/` – eine versteckte Abhängigkeit.

## Entscheidung

- Gemeinsamer Code liegt in **`llm.py`**: LM Studio steuern (Server, Laden, Entladen, Anfrage),
  Bildaufbereitung, Prompt, HTML→Text, Strukturfolge, `.env`-Laden, gemeinsame CLI-Optionen.
- `llm.py` kennt Paperless nicht. Paperless-Zugriff steckt nur in `paperplus.py`.
- `paperplus.py` und `evaluate.py` importieren nur `llm.py`, nie einander.
- `evaluate.py` ruft das Modell selbst auf den Fotos in `referenz/` auf und schreibt nach
  `benchmark/`. Die Tesseract-Basislinie liegt als `referenz/*/tesseract.txt` bei den Referenzen.

## Konsequenzen

- Kein doppelter Code; Änderungen an Prompt oder Bildaufbereitung wirken in beiden Teilen gleich,
  der Benchmark misst also genau das, was beim Anreichern passiert.
- Beide Teile hängen an `llm.py`; Änderungen dort betreffen immer beide.
- Die in ADR 0001 genannte Lücke („`evaluate.py` ruft das LLM noch nicht selbst auf“) ist geschlossen.
