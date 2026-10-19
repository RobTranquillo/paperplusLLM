#!/usr/bin/env python3
"""paperplusLLM – Benchmarken: ein lokales LLM anhand der Referenzdokumente bewerten.

Unabhängig von Paperless und von paperplus.py. Arbeitet nur mit:
  referenz/<doc-id>_<titel>/original.<ext>      Foto/Scan
  referenz/<doc-id>_<titel>/ground_truth.html   vom Menschen korrigierte Fassung
  referenz/<doc-id>_<titel>/tesseract.txt       optional: Tesseract-Text als Basislinie

Ergebnisse:
  benchmark/<doc-id>_<titel>/<modell>.html      Antwort des Modells
  benchmark/bewertung.csv                        alle Werte

Metriken (Text aus dem HTML extrahiert, Leerraum normalisiert, Bilder ignoriert):
  Zeichen   = 1 - CER  (Zeichenfehlerrate, Levenshtein auf Zeichen)
  Wörter    = 1 - WER  (Wortfehlerrate, Levenshtein auf Wörtern)
  Struktur  = Ähnlichkeit der Abfolge der HTML-Strukturelemente (h1, p, table, li …)
Alle Werte in Prozent, 100 % = identisch mit der Referenz.

Aufruf:  python3 evaluate.py                  # eingestelltes Modell auf alle Referenzen
         python3 evaluate.py 210              # nur bestimmte Dokument-IDs
         python3 evaluate.py --model <key>    # anderes Modell
         python3 evaluate.py --score-only     # nur vorhandene Ergebnisse neu bewerten
"""
import argparse
import csv
import difflib
import re
import sys
from pathlib import Path

import llm
from llm import die

REF_DIR = llm.PROJECT_DIR / "referenz"
BENCH_DIR = llm.PROJECT_DIR / "benchmark"
GROUND_TRUTH = "ground_truth.html"
TESSERACT = "tesseract.txt"


# ---------------------------------------------------------------- Metriken

def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


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


def read_candidate(path):
    """Gibt (normalisierter Text, Strukturfolge oder None) zurück."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        return normalize(llm.html_to_text(raw, cell_sep=" ")), llm.html_structure(raw)
    return normalize(raw), None


# ---------------------------------------------------------------- Ablauf

def find_original(ref):
    for f in sorted(ref.glob("original.*")):
        if f.suffix.lower() in llm.SUPPORTED_EXTS:
            return f
    return None


def evaluate_ref(ref):
    """Bewertet alle Modellantworten und die Tesseract-Basislinie zu einer Referenz."""
    doc_id = ref.name.split("_", 1)[0]
    ref_text, ref_struct = read_candidate(ref / GROUND_TRUTH)
    candidates = []
    if (ref / TESSERACT).exists():
        candidates.append(("tesseract (paperless)", ref / TESSERACT))
    candidates += [(f.stem, f) for f in sorted((BENCH_DIR / ref.name).glob("*.html"))]

    rows = []
    for name, f in candidates:
        hyp_text, hyp_struct = read_candidate(f)
        rows.append({"dokument": doc_id, "modell": name, **score(ref_text, ref_struct, hyp_text, hyp_struct)})
    return rows


def fmt(v):
    return "–" if v is None else f"{v * 100:5.1f} %"


def print_table(rows):
    w = max(len(r["modell"]) for r in rows)
    print(f"\n{'Dok.':>6}  {'Modell':<{w}}  {'Zeichen':>8}  {'Wörter':>8}  {'Struktur':>8}")
    print("-" * (w + 38))
    for r in rows:
        print(f"{r['dokument']:>6}  {r['modell']:<{w}}  {fmt(r['zeichen']):>8}  "
              f"{fmt(r['woerter']):>8}  {fmt(r['struktur']):>8}")


def write_csv(rows):
    BENCH_DIR.mkdir(exist_ok=True)
    target = BENCH_DIR / "bewertung.csv"
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["dokument", "modell", "zeichen", "woerter", "struktur"])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})
    print(f"\nGespeichert: {target.relative_to(llm.PROJECT_DIR)}")


def run_model(args, refs):
    """Lässt das Modell alle Referenzfotos lesen und speichert die Antworten in benchmark/."""
    lm = llm.LMStudio()
    lm.start_server()
    model_id = lm.load_model(args.model, args.context_length)
    try:
        for ref in refs:
            original = find_original(ref)
            if not original:
                print(f"✗ {ref.name}: keine unterstützte original.*-Datei", file=sys.stderr)
                continue
            try:
                print(f"… {ref.name}: an {model_id}")
                html, usage, seconds, n_images = lm.transcribe_file(
                    model_id, original, llm.PROMPT, args.max_size, args.max_pages, args.timeout)
                target = BENCH_DIR / ref.name / llm.model_filename(args.model)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(html + "\n", encoding="utf-8")
                print(f"✓ {ref.name}: {n_images} Bild(er), {seconds:.0f} s, "
                      f"{usage.get('completion_tokens', '?')} Tokens")
            except Exception as e:
                print(f"✗ {ref.name}: {e}", file=sys.stderr)
    finally:
        if not args.keep_loaded:
            lm.unload()


def main():
    llm.load_dotenv()

    ap = argparse.ArgumentParser(description="Lokales LLM anhand der Referenzdokumente bewerten.")
    ap.add_argument("ids", nargs="*", type=int, help="nur diese Dokument-IDs (Standard: alle Referenzen)")
    ap.add_argument("--score-only", action="store_true", help="LLM nicht aufrufen, nur vorhandene Ergebnisse bewerten")
    llm.add_llm_arguments(ap)
    args = ap.parse_args()

    refs = sorted(p for p in REF_DIR.glob("*_*") if (p / GROUND_TRUTH).exists()) if REF_DIR.exists() else []
    if args.ids:
        wanted = {str(i) for i in args.ids}
        refs = [p for p in refs if p.name.split("_", 1)[0] in wanted]
    if not refs:
        die(f"Keine Referenzen mit {GROUND_TRUTH} in {REF_DIR.name}/ gefunden.")
    print(f"{len(refs)} Referenz(en): {', '.join(p.name.split('_', 1)[0] for p in refs)}")

    if not args.score_only:
        if not args.model:
            die("Kein Modell angegeben (--model oder LMSTUDIO_MODEL).")
        run_model(args, refs)

    rows = [r for ref in refs for r in evaluate_ref(ref)]
    if not rows:
        die("Keine Ergebnisse zum Bewerten gefunden.")
    print_table(rows)
    write_csv(rows)


if __name__ == "__main__":
    main()
