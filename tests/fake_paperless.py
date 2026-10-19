"""Minimaler Paperless-ngx-Ersatz für die Tests: ein echter HTTP-Server auf localhost.

Unterstützt genau die Endpunkte, die paperplus.py benutzt, und zeichnet alle Anfragen auf:
  GET   /api/documents/            (Filter tags__id__none / tags__id__all, fields, page_size, page)
  GET   /api/documents/<id>/
  GET   /api/documents/<id>/download/[?original=true]
  PATCH /api/documents/<id>/
  GET   /api/tags/?name__iexact=…
  POST  /api/tags/
Alle Daten sind erfunden.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

TOKEN = "test-token"


class FakePaperless:
    def __init__(self):
        self.token = TOKEN
        self.docs = {}          # id -> Dokument-Dict (wie die Paperless-API es liefert)
        self.files = {}         # id -> {"original": bytes, "archive": bytes}
        self.tags = []          # [{"id": 1, "name": "…"}]
        self.requests = []      # [(methode, pfad, query-dict, body)]
        self.max_page_size = 100
        self.force_status = None    # z. B. 403 → jede Anfrage antwortet mit diesem Status
        self.fail = {}              # (methode, pfad-präfix) -> status
        self.on_document_get = {}   # id -> callable(doc, anzahl_abrufe); läuft NACH der Antwort
        self._get_counts = {}
        self.last_headers = {}
        self._server = None
        self.url = None

    # ------------------------------------------------------------ Aufbau
    def add_tag(self, name):
        tag = {"id": max([t["id"] for t in self.tags] + [0]) + 1, "name": name}
        self.tags.append(tag)
        return tag["id"]

    def add_document(self, doc_id, title="Testdokument", file_name="foto.jpg", mime="image/jpeg",
                     tags=(), content="Tesseract-Text", archived=False, original=b"ORIGINAL", archive=b"ARCHIV"):
        self.docs[doc_id] = {
            "id": doc_id, "title": title, "original_file_name": file_name, "mime_type": mime,
            "tags": list(tags), "content": content,
            "archived_file_name": f"{doc_id}.pdf" if archived else None,
        }
        self.files[doc_id] = {"original": original, "archive": archive}
        return self.docs[doc_id]

    # ------------------------------------------------------------ Auswertung
    def calls(self, method=None, prefix=None):
        return [r for r in self.requests
                if (method is None or r[0] == method) and (prefix is None or r[1].startswith(prefix))]

    def patches(self):
        return self.calls("PATCH", "/api/documents/")

    # ------------------------------------------------------------ Server
    def start(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload=None, raw=None):
                body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b"")
                self.send_response(status)
                self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method):
                parts = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                state.requests.append((method, parts.path, query, body))
                state.last_headers = dict(self.headers)

                if self.headers.get("Authorization") != f"Token {state.token}":
                    return self._send(401, {"detail": "Ungültiges Token"})
                if state.force_status:
                    return self._send(state.force_status, {"detail": "erzwungen"})
                for (m, prefix), status in state.fail.items():
                    if m == method and parts.path.startswith(prefix):
                        return self._send(status, {"detail": "injizierter Fehler"})
                self._route(method, parts, query, body)

            def _route(self, method, parts, query, body):
                path = parts.path.rstrip("/")
                if path == "/api/documents" and method == "GET":
                    return self._send(200, state._list_documents(query, parts))
                if path == "/api/tags" and method == "GET":
                    wanted = query.get("name__iexact", "").lower()
                    found = [t for t in state.tags if not wanted or t["name"].lower() == wanted]
                    return self._send(200, {"count": len(found), "next": None, "results": found})
                if path == "/api/tags" and method == "POST":
                    tag = {"id": state.add_tag(body["name"]), **body}
                    state.tags[-1].update(body)
                    return self._send(201, tag)
                segs = path.split("/")  # ['', 'api', 'documents', '<id>', ('download')]
                if len(segs) >= 4 and segs[2] == "documents" and segs[3].isdigit():
                    doc_id = int(segs[3])
                    if doc_id not in state.docs:
                        return self._send(404, {"detail": "Nicht gefunden"})
                    if len(segs) == 5 and segs[4] == "download" and method == "GET":
                        key = "original" if query.get("original") == "true" else "archive"
                        return self._send(200, raw=state.files[doc_id][key])
                    if len(segs) == 4 and method == "GET":
                        doc = json.loads(json.dumps(state.docs[doc_id]))
                        n = state._get_counts[doc_id] = state._get_counts.get(doc_id, 0) + 1
                        self._send(200, doc)
                        if doc_id in state.on_document_get:
                            state.on_document_get[doc_id](state.docs[doc_id], n)
                        return
                    if len(segs) == 4 and method == "PATCH":
                        state.docs[doc_id].update(body)
                        return self._send(200, state.docs[doc_id])
                self._send(404, {"detail": "unbekannter Endpunkt"})

            def do_GET(self):
                self._handle("GET")

            def do_PATCH(self):
                self._handle("PATCH")

            def do_POST(self):
                self._handle("POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        # kurzes Abfrageintervall, sonst wartet shutdown() pro Test bis zu 0,5 s
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def _list_documents(self, query, parts):
        docs = sorted(self.docs.values(), key=lambda d: d["id"], reverse=True)
        if "tags__id__none" in query:
            bad = {int(x) for x in query["tags__id__none"].split(",")}
            docs = [d for d in docs if not bad & set(d["tags"])]
        if "tags__id__all" in query:
            need = {int(x) for x in query["tags__id__all"].split(",")}
            docs = [d for d in docs if need <= set(d["tags"])]
        size = min(int(query.get("page_size", 25)), self.max_page_size)
        page = int(query.get("page", 1))
        chunk = docs[(page - 1) * size: page * size]
        if "fields" in query:
            keep = query["fields"].split(",")
            chunk = [{k: v for k, v in d.items() if k in keep} for d in chunk]
        nxt = None
        if page * size < len(docs):
            nxt = f"{self.url}/api/documents/?" + urlencode({**query, "page": page + 1})
        return {"count": len(docs), "next": nxt, "previous": None, "results": chunk}
