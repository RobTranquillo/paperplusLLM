#!/usr/bin/env python3
"""paperplusLLM – Anreichern: Paperless-Dokumente mit dem eingestellten LLM lesen und den
erkannten Text in Paperless hinterlegen.

Auswahl ohne IDs (ADR 0004): alle Fotos (image/*) ohne Tag „llm-angereichert“
und alle Dokumente mit Tag „llm-ausstehend“ (z. B. als PDF abgelegte Fotos).

Ablauf pro Dokument (einzeln, ein Abbruch verliert nichts):
  1. Verbindung zu Paperless prüfen, sonst Abbruch
  2. Originaldatei lokal ablegen (Eingabe für das LLM)
  3. LM Studio-Server starten und das eingestellte Modell laden (nur wenn es etwas zu tun gibt)
  4. Dokument an das Modell geben, HTML-Antwort lokal speichern
  5. Reinen Text aus dem HTML + Markierung ins Feld "content" schreiben,
     Tag „llm-angereichert“ setzen, „llm-ausstehend“ entfernen

Die Markierung (MARKER) steht sowohl im Text als auch als Tag am Dokument. Fehlt sie im Text
bei gesetztem Tag, wurde der Text vermutlich durch eine neue Tesseract-OCR überschrieben.

Beispiele:
  python3 paperplus.py                 # alle ausstehenden Dokumente (siehe oben)
  python3 paperplus.py --auto          # dasselbe für den Zeitplan: Netzteil-Check, Mitteilung
  python3 paperplus.py --latest 3      # die drei neuesten ausstehenden
  python3 paperplus.py 1234 1240       # bestimmte IDs
  python3 paperplus.py --no-write 1234 # nur lokal, Paperless nicht verändern
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import llm
from llm import die

DEFAULT_PAPERLESS_URL = "http://bfds:30070"
MARKER = "llm-angereichert"
QUEUE_TAG = "llm-ausstehend"
IMAGE_MIME_PREFIX = "image/"


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

    def check_connection(self, quiet_if_offline=False):
        """Erreichbarkeit und Token prüfen. quiet_if_offline: unterwegs still beenden (Zeitplan)."""
        try:
            self.request("/api/documents/?page_size=1", timeout=10)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                die(f"Paperless erreichbar, aber Token ungültig oder ohne Rechte (HTTP {e.code}).")
            die(f"Paperless antwortet mit HTTP {e.code}.")
        except (urllib.error.URLError, OSError) as e:
            if quiet_if_offline:
                print(f"Paperless unter {self.url} nicht erreichbar – nichts zu tun.")
                sys.exit(0)
            die(f"Paperless unter {self.url} nicht erreichbar: {getattr(e, 'reason', e)}")
        print(f"✓ Paperless erreichbar: {self.url}")

    def list_all(self, path):
        """Alle Seiten einer Listenabfrage einsammeln."""
        results = []
        while path:
            res = self.request(path)
            results += res["results"]
            nxt = res.get("next")
            path = (urllib.parse.urlsplit(nxt).path + "?" + urllib.parse.urlsplit(nxt).query) if nxt else None
        return results

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


def pending_ids(pl, marker_tag, queue_tag):
    """Auswahl laut ADR 0004: Fotos ohne Marker-Tag + alles mit Warteschlangen-Tag. Neueste zuerst."""
    query = f"/api/documents/?page_size=100&fields=id,mime_type"
    if marker_tag:
        query += f"&tags__id__none={marker_tag}"
    ids = {d["id"] for d in pl.list_all(query) if (d.get("mime_type") or "").startswith(IMAGE_MIME_PREFIX)}
    if queue_tag:
        ids |= {d["id"] for d in pl.list_all(f"/api/documents/?page_size=100&fields=id&tags__id__all={queue_tag}")}
    return sorted(ids, reverse=True)


def on_ac_power():
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    return "AC Power" in out or "Battery Power" not in out


def notify(message):
    """macOS-Mitteilung (Fehler werden ignoriert, z. B. ohne grafische Sitzung)."""
    script = f'display notification {json.dumps(message)} with title "paperplusLLM"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def build_content(text, model):
    """Text für das Paperless-Feld content: LLM-Text + Markierungszeile am Ende."""
    return f"{text}\n\n{MARKER} ({model})"


# ---------------------------------------------------------------- Ablauf

def main():
    llm.load_dotenv()

    ap = argparse.ArgumentParser(description="Paperless-Dokumente mit dem eingestellten LLM anreichern.")
    ap.add_argument("ids", nargs="*", type=int, help="Paperless-Dokument-IDs (sonst alle ausstehenden, siehe ADR 0004)")
    ap.add_argument("--latest", type=int, help="nur die N neuesten der ausstehenden Dokumente")
    ap.add_argument("--auto", action="store_true", help="für den Zeitplan: nur am Netzteil, still ohne Paperless, Mitteilung am Ende")
    ap.add_argument("--out", default=os.environ.get("PAPERPLUS_OUT", str(llm.PROJECT_DIR / "ausgabe")), help="lokaler Ausgabeordner")
    ap.add_argument("--skip-llm", action="store_true", help="nur Dokumente aus Paperless laden, LM Studio/Modell überspringen")
    ap.add_argument("--no-write", action="store_true", help="Ergebnis nur lokal ablegen, Paperless nicht verändern")
    ap.add_argument("--force", action="store_true", help=f"auch Dokumente verarbeiten, die bereits den Tag „{MARKER}“ haben")
    llm.add_llm_arguments(ap)
    args = ap.parse_args()

    if args.auto:
        print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        if not on_ac_power():
            print("Mac läuft auf Akku – übersprungen.")
            sys.exit(0)
    if not args.model and not args.skip_llm:
        die("Kein Modell angegeben (--model oder LMSTUDIO_MODEL).")
    token = os.environ.get("PAPERLESS_TOKEN")
    if not token:
        die("PAPERLESS_TOKEN fehlt (in .env oder als Umgebungsvariable setzen).")

    # 1) Verbindung prüfen, Dokumente auswählen
    pl = Paperless(os.environ.get("PAPERLESS_URL", DEFAULT_PAPERLESS_URL), token)
    pl.check_connection(quiet_if_offline=args.auto)

    write = not (args.no_write or args.skip_llm)
    marker_tag = pl.tag_id(MARKER, create=write)
    queue_tag = pl.tag_id(QUEUE_TAG)

    if args.ids:
        ids = args.ids
    else:
        ids = pending_ids(pl, marker_tag, queue_tag)
        print(f"{len(ids)} Dokument(e) ausstehend")
        if args.latest:
            ids = ids[:args.latest]
            print(f"davon die {len(ids)} neuesten: {', '.join(f'#{i}' for i in ids)}")
    if not ids:
        print("Nichts zu tun.")
        sys.exit(0)

    out_root = Path(args.out).expanduser().resolve()
    if args.skip_llm:
        for doc_id in ids:
            try:
                store_document(pl, doc_id, out_root)
            except Exception as e:
                print(f"✗ #{doc_id}: {e}", file=sys.stderr)
        print("LLM-Schritte übersprungen (--skip-llm).")
        sys.exit(0)

    lm = None
    done, errors = 0, 0
    try:
        for n, doc_id in enumerate(ids, 1):
            try:
                # 2) Original holen; Dokumente mit Marker überspringen, außer sie stehen in der Warteschlange
                folder, original, doc = store_document(pl, doc_id, out_root)
                tags = set(doc.get("tags", []))
                if marker_tag in tags and queue_tag not in tags and not args.force:
                    print(f"  #{doc_id} hat bereits den Tag „{MARKER}“ – übersprungen (--force zum Erzwingen)")
                    continue

                # 3) LM Studio erst starten, wenn es wirklich etwas zu tun gibt
                if lm is None:
                    lm = llm.LMStudio()
                    lm.start_server()
                    model_id = lm.load_model(args.model, args.context_length)

                # 4) Modell lesen lassen, HTML lokal speichern
                print(f"… [{n}/{len(ids)}] #{doc_id}: an {model_id}")
                html, usage, seconds, n_images = lm.transcribe_file(
                    model_id, original, llm.PROMPT, args.max_size, args.max_pages, args.timeout)
                target = folder / llm.model_filename(args.model)
                target.write_text(html + "\n", encoding="utf-8")
                print(f"✓ #{doc_id}: {target.name} ({n_images} Bild(er), {seconds:.0f} s, "
                      f"{usage.get('completion_tokens', '?')} Tokens)")

                text = llm.html_to_text(html)
                if not text:
                    raise RuntimeError("LLM hat keinen Text geliefert – Paperless bleibt unverändert")

                # 5) Nach Paperless schreiben; Tags frisch lesen, um zwischenzeitliche Änderungen nicht zu überschreiben
                if write:
                    tags = set(pl.document(doc_id).get("tags", []))
                    tags = (tags | {marker_tag}) - {queue_tag}
                    pl.update(doc_id, {"content": build_content(text, args.model), "tags": sorted(tags)})
                    print(f"✓ #{doc_id}: Inhalt in Paperless ersetzt ({len(text)} Zeichen), Tag „{MARKER}“ gesetzt")
                done += 1
            except Exception as e:
                errors += 1
                print(f"✗ #{doc_id}: {e}", file=sys.stderr)
    finally:
        if lm and not args.keep_loaded:
            lm.unload()

    print(f"Fertig: {done} angereichert, {errors} Fehler.")
    if args.auto and (done or errors):
        notify(f"{done} Dokument(e) angereichert" + (f", {errors} Fehler" if errors else ""))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
