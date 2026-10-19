#!/usr/bin/env python3
"""paperplusLLM – Anreichern: Paperless-Dokumente mit dem eingestellten LLM lesen und den
erkannten Text in Paperless hinterlegen.

Ablauf:
  1. Verbindung zu Paperless prüfen, sonst Abbruch
  2. Originaldatei lokal ablegen (Eingabe für das LLM)
  3. LM Studio-Server starten und das eingestellte Modell laden
  4. Dokument an das Modell geben, HTML-Antwort lokal speichern
  5. Reinen Text aus dem HTML + Markierung ins Feld "content" schreiben, Tag setzen

Die Markierung (MARKER) steht sowohl im Text als auch als Tag am Dokument. Fehlt sie im Text
bei gesetztem Tag, wurde der Text vermutlich durch eine neue Tesseract-OCR überschrieben:
  Suche in Paperless:  tag:llm-angereichert -content:llm-angereichert   (siehe README)

Beispiele:
  python3 paperplus.py                 # neuestes Dokument
  python3 paperplus.py --latest 3      # die drei neuesten
  python3 paperplus.py 1234 1240       # bestimmte IDs
  python3 paperplus.py --no-write 1234 # nur lokal, Paperless nicht verändern
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import llm
from llm import die

DEFAULT_PAPERLESS_URL = "http://bfds:30070"
MARKER = "llm-angereichert"


# ---------------------------------------------------------------- Paperless

class Paperless:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def request(self, path, method="GET", data=None, raw=False, timeout=60):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, data=body, method=method)
        req.add_header("Authorization", f"Token {self.token}")
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
        return payload if raw else (json.loads(payload) if payload else None)

    def check_connection(self):
        """Erreichbarkeit und Token prüfen."""
        try:
            self.request("/api/documents/?page_size=1", timeout=10)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                die(f"Paperless erreichbar, aber Token ungültig oder ohne Rechte (HTTP {e.code}).")
            die(f"Paperless antwortet mit HTTP {e.code}.")
        except (urllib.error.URLError, OSError) as e:
            die(f"Paperless unter {self.url} nicht erreichbar: {getattr(e, 'reason', e)}")
        print(f"✓ Paperless erreichbar: {self.url}")

    def latest_ids(self, n):
        res = self.request(f"/api/documents/?ordering=-added&page_size={n}&fields=id")
        return [d["id"] for d in res["results"]]

    def document(self, doc_id):
        return self.request(f"/api/documents/{doc_id}/")

    def download(self, doc_id, original=True):
        q = "?original=true" if original else ""
        return self.request(f"/api/documents/{doc_id}/download/{q}", raw=True, timeout=300)

    def update(self, doc_id, fields):
        return self.request(f"/api/documents/{doc_id}/", method="PATCH", data=fields)

    def tag_id(self, name, create=False):
        res = self.request("/api/tags/?name__iexact=" + urllib.parse.quote(name))
        if res["results"]:
            return res["results"][0]["id"]
        if not create:
            return None
        # matching_algorithm 0 = "Keine": Paperless vergibt den Tag nie automatisch
        tag = self.request("/api/tags/", method="POST", data={"name": name, "matching_algorithm": 0})
        print(f"✓ Tag „{name}“ in Paperless angelegt")
        return tag["id"]


def store_document(pl, doc_id, out_root):
    """Originaldatei lokal in einen eigenen Ordner legen."""
    doc = pl.document(doc_id)
    folder = out_root / f"{doc_id}_{llm.slugify(doc.get('title'))}"
    folder.mkdir(parents=True, exist_ok=True)

    ext = Path(doc.get("original_file_name") or "").suffix.lower() or ".bin"
    if ext in llm.SUPPORTED_EXTS:
        original = folder / f"original{ext}"
        if not original.exists():
            original.write_bytes(pl.download(doc_id, original=True))
    elif doc.get("archived_file_name"):
        # z. B. Office-Dateien oder E-Mails: archivierte PDF-Version verwenden
        original = folder / "original.pdf"
        if not original.exists():
            original.write_bytes(pl.download(doc_id, original=False))
    else:
        raise RuntimeError(f"Dateityp {ext} wird nicht unterstützt und hat keine PDF-Archivversion")

    shown = folder.relative_to(Path.cwd()) if folder.is_relative_to(Path.cwd()) else folder
    print(f"✓ #{doc_id} „{doc.get('title')}“ → {shown}")
    return folder, original, doc


def build_content(text, model):
    """Text für das Paperless-Feld content: LLM-Text + Markierungszeile am Ende."""
    return f"{text}\n\n{MARKER} ({model})"


# ---------------------------------------------------------------- Ablauf

def main():
    llm.load_dotenv()

    ap = argparse.ArgumentParser(description="Paperless-Dokumente mit dem eingestellten LLM anreichern.")
    ap.add_argument("ids", nargs="*", type=int, help="Paperless-Dokument-IDs (sonst die neuesten)")
    ap.add_argument("--latest", type=int, default=1, help="Anzahl neuester Dokumente, wenn keine IDs angegeben (Standard: 1)")
    ap.add_argument("--out", default=os.environ.get("PAPERPLUS_OUT", str(llm.PROJECT_DIR / "ausgabe")), help="lokaler Ausgabeordner")
    ap.add_argument("--with-ocr", action="store_true", help="Paperless-Text als Hilfe mit an das Modell geben")
    ap.add_argument("--skip-llm", action="store_true", help="nur Dokumente aus Paperless laden, LM Studio/Modell überspringen")
    ap.add_argument("--no-write", action="store_true", help="Ergebnis nur lokal ablegen, Paperless nicht verändern")
    ap.add_argument("--force", action="store_true", help=f"auch Dokumente verarbeiten, die bereits den Tag „{MARKER}“ haben")
    llm.add_llm_arguments(ap)
    args = ap.parse_args()

    if not args.model and not args.skip_llm:
        die("Kein Modell angegeben (--model oder LMSTUDIO_MODEL).")
    token = os.environ.get("PAPERLESS_TOKEN")
    if not token:
        die("PAPERLESS_TOKEN fehlt (in .env oder als Umgebungsvariable setzen).")

    # 1) Verbindung prüfen
    pl = Paperless(os.environ.get("PAPERLESS_URL", DEFAULT_PAPERLESS_URL), token)
    pl.check_connection()

    ids = args.ids or pl.latest_ids(args.latest)
    if not ids:
        die("Keine Dokumente gefunden.")

    write = not (args.no_write or args.skip_llm)
    marker_tag = pl.tag_id(MARKER, create=write)

    # 2) Dokumente + vorhandenen Text lokal ablegen
    out_root = Path(args.out).expanduser().resolve()
    docs = []
    for doc_id in ids:
        try:
            folder, original, doc = llm_input = store_document(pl, doc_id, out_root)
        except Exception as e:
            print(f"✗ #{doc_id}: {e}", file=sys.stderr)
            continue
        if marker_tag in doc.get("tags", []) and not args.force and not args.skip_llm:
            print(f"  #{doc_id} hat bereits den Tag „{MARKER}“ – übersprungen (--force zum Erzwingen)")
            continue
        docs.append(llm_input)

    if args.skip_llm:
        print("LLM-Schritte übersprungen (--skip-llm).")
        sys.exit(0)
    if not docs:
        print("Nichts zu tun.")
        sys.exit(0)

    # 3) LM Studio starten und Modell laden
    lm = llm.LMStudio()
    lm.start_server()
    model_id = lm.load_model(args.model, args.context_length)

    # 4) + 5) Dokumente an das Modell geben, lokal speichern, nach Paperless schreiben
    errors = 0
    try:
        for folder, original, doc in docs:
            prompt, suffix = llm.PROMPT, ""
            # Frühere Fassungen von content hält Paperless selbst im Änderungsverlauf vor
            ocr = doc.get("content") or ""
            if args.with_ocr and ocr.strip() and MARKER not in ocr:
                prompt += llm.PROMPT_OCR_HINT.format(ocr=ocr)
                suffix = "_mit-ocr"
            try:
                print(f"… #{doc['id']}: an {model_id}")
                html, usage, seconds, n_images = lm.transcribe_file(
                    model_id, original, prompt, args.max_size, args.max_pages, args.timeout)
                target = folder / llm.model_filename(args.model, suffix)
                target.write_text(html + "\n", encoding="utf-8")
                print(f"✓ #{doc['id']}: {target.name} ({n_images} Bild(er), {seconds:.0f} s, "
                      f"{usage.get('completion_tokens', '?')} Tokens)")

                text = llm.html_to_text(html)
                if not text:
                    raise RuntimeError("LLM hat keinen Text geliefert – Paperless bleibt unverändert")
                if write:
                    tags = sorted(set(doc.get("tags", [])) | {marker_tag})
                    pl.update(doc["id"], {"content": build_content(text, args.model), "tags": tags})
                    print(f"✓ #{doc['id']}: Inhalt in Paperless ersetzt ({len(text)} Zeichen), Tag „{MARKER}“ gesetzt")
            except Exception as e:
                errors += 1
                print(f"✗ #{doc['id']}: {e}", file=sys.stderr)
    finally:
        if not args.keep_loaded:
            lm.unload()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
