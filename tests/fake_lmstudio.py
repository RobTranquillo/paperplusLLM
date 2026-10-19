"""Ersatz für LM Studio in den Tests – ohne LM Studio, ohne Modell, ohne macOS.

FakeLms        ausführbares Skript, das die CLI `lms` nachahmt (server/ps/ls/load/unload).
               Das Verhalten steht in einer JSON-Datei, jeder Aufruf wird protokolliert.
FakeLmServer   HTTP-Server mit /v1/chat/completions (OpenAI-kompatibel), zeichnet Anfragen auf.
"""
import json
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LMS_SCRIPT = '''#!{python}
import json, os, sys

state = json.load(open(os.environ["FAKE_LMS_STATE"]))
args = sys.argv[1:]
with open(state["log"], "a") as f:
    f.write(json.dumps(args) + "\\n")


def out(value):
    sys.stdout.write(value if isinstance(value, str) else json.dumps(value))


def finish(rc, err):
    if rc:
        print(err, file=sys.stderr)
    sys.exit(rc)


if args[:2] == ["server", "status"]:
    out(state["status"])
elif args[:2] == ["server", "start"]:
    finish(state["server_start_rc"], state["server_start_err"])
elif args[0] == "ps":
    out(state["ps"])
elif args[0] == "ls":
    out(state["ls"])
elif args[0] == "load":
    finish(state["load_rc"], state["load_err"])
elif args[0] == "unload":
    finish(state["unload_rc"], "")
else:
    finish(2, "unbekannter Befehl")
'''

DEFAULTS = {
    "status": {"running": False},
    "server_start_rc": 0, "server_start_err": "",
    "ps": [], "ls": [],
    "load_rc": 0, "load_err": "",
    "unload_rc": 0,
}


class FakeLms:
    def __init__(self, tmp_path, monkeypatch):
        self.bin_dir = tmp_path / "fake-bin"
        self.bin_dir.mkdir()
        self.script = self.bin_dir / "lms"
        self.script.write_text(LMS_SCRIPT.format(python=sys.executable))
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.state_file = tmp_path / "lms-state.json"
        self.log = tmp_path / "lms-calls.log"
        self.state = {**DEFAULTS, "log": str(self.log)}
        self.configure()
        monkeypatch.setenv("FAKE_LMS_STATE", str(self.state_file))
        monkeypatch.setenv("PATH", f"{self.bin_dir}:/usr/bin:/bin")

    def configure(self, **changes):
        self.state.update(changes)
        self.state_file.write_text(json.dumps(self.state))

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def commands(self):
        """Nur der Befehl ohne Argumente, z. B. ['server status', 'ps', 'load']."""
        return [" ".join(c[:2]) if c[0] == "server" else c[0] for c in self.calls()]


class FakeLmServer:
    def __init__(self):
        self.requests = []   # geparste JSON-Bodies
        self.headers = []
        self.status = 200
        self.response = {"choices": [{"message": {"content": "<p>Antwort</p>"}, "finish_reason": "stop"}],
                         "usage": {"completion_tokens": 7}}
        self.raw_error = "Fehlertext"
        self.delay = 0.0
        self._server = None
        self.url = None

    def start(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                state.requests.append((self.path, json.loads(self.rfile.read(length))))
                state.headers.append(dict(self.headers))
                if state.delay:
                    time.sleep(state.delay)
                if state.status != 200:
                    body = state.raw_error.encode()
                    self.send_response(state.status)
                else:
                    body = json.dumps(state.response).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass  # Client hat wegen Timeout schon aufgelegt

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def reply(self, content=None, reasoning=None, finish="stop", usage=None, omit_usage=False):
        message = {}
        if content is not None:
            message["content"] = content
        if reasoning is not None:
            message["reasoning_content"] = reasoning
        self.response = {"choices": [{"message": message, "finish_reason": finish}]}
        if not omit_usage:
            self.response["usage"] = usage if usage is not None else {"completion_tokens": 7}


HTML = '<div data-label="Text"><p>Hallo Welt<br/>Zweite Zeile</p></div>'


class FakeLM:
    """Ersatz für llm.LMStudio: kein lms, kein Modell, keine macOS-Werkzeuge."""
    instances = []
    responder = None  # callable(original_path) -> html; Standard: HTML

    def __init__(self, base_url=None):
        self.events, self.transcribed, self.options = [], [], []
        FakeLM.instances.append(self)

    def start_server(self):
        self.events.append("start_server")

    def load_model(self, model_key, context_length):
        self.events.append(("load_model", model_key, context_length))
        return model_key

    def transcribe_file(self, model_id, original, prompt=None, max_size=2000, max_pages=5, timeout=900):
        self.transcribed.append(original)
        self.options.append((max_size, max_pages, timeout))
        html = FakeLM.responder(original) if FakeLM.responder else HTML
        return html, {"completion_tokens": 42}, 1.0, 1

    def unload(self):
        self.events.append("unload")
