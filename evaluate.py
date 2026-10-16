#!/usr/bin/env python3
"""Vergleicht LLM-Ergebnisse (ausgabe/) mit den Referenzen (referenz/).

Referenz:  referenz/<doc-id>_<titel>/ground_truth.html  (+ original.<ext>)
Ergebnis:  ausgabe/<doc-id>_<titel>/<modell>.html, paperless_content.txt (Tesseract)

Metriken (Text wird vorher aus dem HTML extrahiert, Leerraum normalisiert, Bilder ignoriert):
  Zeichen   = 1 - CER  (Zeichenfehlerrate, Levenshtein auf Zeichen)
  Wörter    = 1 - WER  (Wortfehlerrate, Levenshtein auf Wörtern)
  Struktur  = Ähnlichkeit der Abfolge der HTML-Strukturelemente (h1, p, table, li …)
Alle Werte in Prozent, 100 % = identisch mit der Referenz.

Aufruf:  python3 evaluate.py            # alle Referenzen
         python3 evaluate.py 220        # nur bestimmte Dokument-IDs
"""
import argparse
import csv
import difflib
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REF_DIR = PROJECT_DIR / "referenz"
OUT_DIR = PROJECT_DIR / "ausgabe"
GROUND_TRUTH = "ground_truth.html"
TESSERACT = "paperless_content.txt"

BLOCK_TAGS = {"p", "div", "br", "tr", "li", "table", "ul", "ol", "section", "header", "footer",
              "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr"}
CELL_TAGS = {"td", "th"}
STRUCTURE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "tr", "td", "th", "ul", "ol", "li"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.structure = [], []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in CELL_TAGS:
            self.parts.append(" ")
        if tag in STRUCTURE_TAGS:
            self.structure.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def parse(text, is_html):
    """Gibt (normalisierter Text, Strukturfolge oder None) zurück."""
    if is_html:
        ex = _Extractor()
        ex.feed(text)
        ex.close()
        text, structure = "".join(ex.parts), ex.structure
    else:
        structure = None
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip(), structure


def levenshtein(a, b):
    """Editierdistanz zwischen zwei Sequenzen (Zeichen oder Wortlisten)."""
    # gemeinsamen Anfang/Ende abschneiden spart bei ähnlichen Texten viel Rechenzeit
    start = 0
    while start < len(a) and start < len(b) and a[start] == b[start]:
        start += 1
    end = 0
    while end < len(a) - start and end < len(b) - start and a[-1 - end] == b[-1 - end]:
        end += 1
    a, b = a[start:len(a) - end], b[start:len(b) - end]
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(ref_text, ref_struct, hyp_text, hyp_struct):
    def rate(ref, hyp):
        return max(0.0, 1 - levenshtein(ref, hyp) / len(ref)) if ref else float(not hyp)

    result = {
        "zeichen": rate(ref_text, hyp_text),
        "woerter": rate(ref_text.split(), hyp_text.split()),
        "struktur": None,
    }
    if ref_struct is not None and hyp_struct is not None:
        result["struktur"] = difflib.SequenceMatcher(None, ref_struct, hyp_struct, autojunk=False).ratio()
    return result


def find_output_dir(doc_id):
    matches = sorted(OUT_DIR.glob(f"{doc_id}_*"))
    return matches[0] if matches else None


def evaluate_doc(ref_folder):
    """Bewertet alle Ergebnisse zu einer Referenz. Gibt Liste von Zeilen-Dicts zurück."""
    doc_id = ref_folder.name.split("_", 1)[0]
    gt_file = ref_folder / GROUND_TRUTH
    if not gt_file.exists():
        return []
    ref_text, ref_struct = parse(gt_file.read_text(encoding="utf-8"), is_html=True)
    out = find_output_dir(doc_id)
    if not out:
        return []

    rows = []
    candidates = sorted(out.glob("*.html"))
    if (out / TESSERACT).exists():
        candidates.insert(0, out / TESSERACT)
    for f in candidates:
        hyp_text, hyp_struct = parse(f.read_text(encoding="utf-8"), is_html=f.suffix == ".html")
        name = "tesseract (paperless)" if f.name == TESSERACT else f.stem
        rows.append({"dokument": doc_id, "modell": name, **score(ref_text, ref_struct, hyp_text, hyp_struct)})
    return rows


def fmt(v):
    return "–" if v is None else f"{v * 100:5.1f} %"


def print_table(rows):
    if not rows:
        print("Keine Ergebnisse zum Vergleichen gefunden.")
        return
    w = max(len(r["modell"]) for r in rows)
    print(f"\n{'Dok.':>6}  {'Modell':<{w}}  {'Zeichen':>8}  {'Wörter':>8}  {'Struktur':>8}")
    print("-" * (w + 38))
    for r in rows:
        print(f"{r['dokument']:>6}  {r['modell']:<{w}}  {fmt(r['zeichen']):>8}  "
              f"{fmt(r['woerter']):>8}  {fmt(r['struktur']):>8}")


def evaluate(doc_ids=None, write_csv=True):
    refs = sorted(p for p in REF_DIR.glob("*_*") if p.is_dir()) if REF_DIR.exists() else []
    if doc_ids:
        wanted = {str(i) for i in doc_ids}
        refs = [p for p in refs if p.name.split("_", 1)[0] in wanted]
    rows = [r for ref in refs for r in evaluate_doc(ref)]
    print_table(rows)
    if write_csv and rows:
        target = OUT_DIR / "bewertung.csv"
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["dokument", "modell", "zeichen", "woerter", "struktur"])
            writer.writeheader()
            for r in rows:
                writer.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})
        print(f"\nGespeichert: {target.relative_to(PROJECT_DIR)}")
    return rows


def main():
    ap = argparse.ArgumentParser(description="LLM-Ergebnisse mit Referenzen vergleichen.")
    ap.add_argument("ids", nargs="*", type=int, help="nur diese Dokument-IDs (Standard: alle Referenzen)")
    args = ap.parse_args()
    if not evaluate(args.ids):
        sys.exit(1)


if __name__ == "__main__":
    main()
