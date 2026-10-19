"""Tests für llm.LMStudio: Steuerung über das (gefakte) `lms` und die HTTP-Schnittstelle."""
import json
import urllib.error

import pytest

import llm

VISION = {"type": "llm", "modelKey": "chandra-ocr-2", "vision": True}
TEXT_ONLY = {"type": "llm", "modelKey": "nur-text"}
EMBEDDING = {"type": "embedding", "modelKey": "embed-1"}


@pytest.fixture
def lm(fake_lms):
    return llm.LMStudio()


# ---------------------------------------------------------------- Konstruktor

def test_standard_url(fake_lms):
    assert llm.LMStudio().base_url == llm.DEFAULT_LMSTUDIO_URL


def test_url_aus_umgebung_ohne_schraegstrich(fake_lms, monkeypatch):
    monkeypatch.setenv("LMSTUDIO_URL", "http://example.test:1/v1/")
    assert llm.LMStudio().base_url == "http://example.test:1/v1"


def test_url_als_argument_hat_vorrang(fake_lms, monkeypatch):
    monkeypatch.setenv("LMSTUDIO_URL", "http://aus-umgebung/v1")
    assert llm.LMStudio("http://argument/v1").base_url == "http://argument/v1"


def test_findet_lms_im_path(fake_lms):
    assert llm.LMStudio().lms == str(fake_lms.script)


def test_findet_lms_ueber_fallback_pfad(tmp_path, monkeypatch):
    leer = tmp_path / "leer"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))
    fallback = tmp_path / "lms"
    fallback.write_text("")
    monkeypatch.setattr(llm, "LMS_FALLBACK", fallback)
    assert llm.LMStudio().lms == str(fallback)


def test_ohne_lms_bricht_ab(tmp_path, monkeypatch, capsys):
    leer = tmp_path / "leer"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))
    monkeypatch.setattr(llm, "LMS_FALLBACK", tmp_path / "gibt-es-nicht")
    with pytest.raises(SystemExit) as exc:
        llm.LMStudio()
    assert exc.value.code == 1
    assert "'lms' nicht gefunden" in capsys.readouterr().err


# ---------------------------------------------------------------- start_server

def test_start_server_laeuft_bereits(fake_lms, lm, capsys):
    fake_lms.configure(status={"running": True})
    lm.start_server()
    assert fake_lms.calls() == [["server", "status", "--json"]]
    assert "läuft bereits" in capsys.readouterr().out


def test_start_server_startet_wenn_noetig(fake_lms, lm, capsys):
    lm.start_server()
    assert fake_lms.commands() == ["server status", "server start"]
    assert "gestartet" in capsys.readouterr().out


@pytest.mark.parametrize("status_ausgabe", ["", "kein json", "[]x"])
def test_start_server_unlesbarer_status_fuehrt_zum_start(fake_lms, lm, status_ausgabe):
    fake_lms.configure(status=status_ausgabe)
    lm.start_server()
    assert fake_lms.commands() == ["server status", "server start"]


def test_start_server_fehlgeschlagen(fake_lms, lm, capsys):
    fake_lms.configure(server_start_rc=1, server_start_err="Port belegt")
    with pytest.raises(SystemExit) as exc:
        lm.start_server()
    assert exc.value.code == 1
    assert "Port belegt" in capsys.readouterr().err


# ---------------------------------------------------------------- load_model

def test_load_model_bereits_geladen_per_modelkey(fake_lms, lm, capsys):
    fake_lms.configure(ps=[{"modelKey": "chandra-ocr-2", "identifier": "chandra-ocr-2:2"}])
    assert lm.load_model("chandra-ocr-2", 16384) == "chandra-ocr-2:2"
    assert fake_lms.commands() == ["ps"]  # nichts geladen, nichts zu entladen
    assert lm.loaded_by_us is None
    assert "bereits geladen" in capsys.readouterr().out


def test_load_model_bereits_geladen_per_identifier(fake_lms, lm):
    fake_lms.configure(ps=[{"modelKey": "x", "identifier": "mein-name"}])
    assert lm.load_model("mein-name", None) == "mein-name"


def test_load_model_laedt_mit_kontextlaenge(fake_lms, lm):
    fake_lms.configure(ls=[VISION])
    assert lm.load_model("chandra-ocr-2", 16384) == "chandra-ocr-2"
    assert fake_lms.calls()[-1] == ["load", "chandra-ocr-2", "--yes", "--identifier", "chandra-ocr-2",
                                    "--context-length", "16384"]
    assert lm.loaded_by_us == "chandra-ocr-2"


def test_load_model_ohne_kontextlaenge(fake_lms, lm):
    fake_lms.configure(ls=[VISION])
    lm.load_model("chandra-ocr-2", None)
    assert "--context-length" not in fake_lms.calls()[-1]


def test_load_model_nicht_heruntergeladen_nennt_alternativen(fake_lms, lm, capsys):
    fake_lms.configure(ls=[VISION, TEXT_ONLY, EMBEDDING])
    with pytest.raises(SystemExit) as exc:
        lm.load_model("fehlt", 16384)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "'fehlt' ist nicht heruntergeladen" in err
    assert "chandra-ocr-2  (Vision)" in err and "nur-text" in err
    assert "embed-1" not in err  # Embedding-Modelle sind keine LLMs
    assert "lms get fehlt" in err
    assert "load" not in fake_lms.commands()


def test_load_model_ohne_installierte_modelle(fake_lms, lm, capsys):
    with pytest.raises(SystemExit):
        lm.load_model("x", 16384)
    assert "(keine)" in capsys.readouterr().err


def test_load_model_ladefehler(fake_lms, lm, capsys):
    fake_lms.configure(ls=[VISION], load_rc=1, load_err="zu wenig Speicher")
    with pytest.raises(SystemExit):
        lm.load_model("chandra-ocr-2", 16384)
    assert "zu wenig Speicher" in capsys.readouterr().err
    assert lm.loaded_by_us is None  # fehlgeschlagen -> nichts zu entladen


def test_load_model_leere_ausgabe_von_ps_gilt_als_keine_modelle(fake_lms, lm):
    fake_lms.configure(ps="", ls=[VISION])
    assert lm.load_model("chandra-ocr-2", 1) == "chandra-ocr-2"


# ---------------------------------------------------------------- unload

def test_unload_nur_selbst_geladene_modelle(fake_lms, lm, capsys):
    lm.unload()
    assert fake_lms.calls() == []

    fake_lms.configure(ls=[VISION])
    lm.load_model("chandra-ocr-2", 1)
    lm.unload()
    assert fake_lms.calls()[-1] == ["unload", "chandra-ocr-2"]
    assert "entladen" in capsys.readouterr().out


def test_unload_ignoriert_fehler(fake_lms, lm):
    fake_lms.configure(ls=[VISION], unload_rc=1)
    lm.load_model("chandra-ocr-2", 1)
    lm.unload()  # darf nicht werfen


def test_bereits_vorher_geladenes_modell_wird_nicht_entladen(fake_lms, lm):
    fake_lms.configure(ps=[{"modelKey": "chandra-ocr-2", "identifier": "chandra-ocr-2"}])
    lm.load_model("chandra-ocr-2", 1)
    lm.unload()
    assert "unload" not in fake_lms.commands()


# ---------------------------------------------------------------- transcribe (HTTP)

@pytest.fixture
def client(lm_server, fake_lms):
    return llm.LMStudio(lm_server.url)


@pytest.fixture
def bilder(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.jpg"
    a.write_bytes(b"PNG-BYTES")
    b.write_bytes(b"JPG-BYTES")
    return [a, b]


def test_transcribe_anfrage_ist_openai_kompatibel(client, lm_server, bilder):
    client.transcribe("modell-x", bilder, "Lies das", timeout=10)
    (path, body), = lm_server.requests
    assert path == "/v1/chat/completions"
    assert lm_server.headers[0]["Content-Type"] == "application/json"
    assert body["model"] == "modell-x"
    assert body["temperature"] == 0 and body["stream"] is False
    (message,) = body["messages"]
    assert message["role"] == "user"
    text, img1, img2 = message["content"]
    assert text == {"type": "text", "text": "Lies das"}
    assert img1["image_url"]["url"].startswith("data:image/png;base64,")
    assert img2["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_transcribe_liefert_text_und_usage(client, lm_server, bilder):
    text, usage = client.transcribe("m", bilder, "p", timeout=10)
    assert text == "<p>Antwort</p>"
    assert usage == {"completion_tokens": 7}


def test_transcribe_nutzt_reasoning_content_wenn_content_fehlt(client, lm_server, bilder):
    lm_server.reply(content="", reasoning="<p>aus reasoning</p>")
    assert client.transcribe("m", bilder, "p", timeout=10)[0] == "<p>aus reasoning</p>"
    lm_server.reply(reasoning="<p>nur reasoning</p>")  # content gar nicht vorhanden
    assert client.transcribe("m", bilder, "p", timeout=10)[0] == "<p>nur reasoning</p>"


def test_transcribe_content_hat_vorrang_vor_reasoning(client, lm_server, bilder):
    lm_server.reply(content="<p>Antwort</p>", reasoning="<p>Gedanken</p>")
    assert client.transcribe("m", bilder, "p", timeout=10)[0] == "<p>Antwort</p>"


def test_transcribe_ganz_leere_antwort_ist_leerer_text(client, lm_server, bilder):
    lm_server.reply()
    assert client.transcribe("m", bilder, "p", timeout=10)[0] == ""


def test_transcribe_ohne_usage(client, lm_server, bilder):
    lm_server.reply(content="x", omit_usage=True)
    assert client.transcribe("m", bilder, "p", timeout=10)[1] == {}


def test_transcribe_warnt_bei_abgeschnittener_antwort(client, lm_server, bilder, capsys):
    lm_server.reply(content="<p>halb", finish="length")
    text, _ = client.transcribe("m", bilder, "p", timeout=10)
    assert text == "<p>halb"
    assert "abgeschnitten" in capsys.readouterr().out


def test_transcribe_http_fehler_enthaelt_status_und_gekuerzten_text(client, lm_server, bilder):
    lm_server.status = 500
    lm_server.raw_error = "X" * 2000
    with pytest.raises(RuntimeError) as exc:
        client.transcribe("m", bilder, "p", timeout=10)
    assert "LM Studio HTTP 500" in str(exc.value)
    assert len(str(exc.value)) < 600


def test_transcribe_timeout(client, lm_server, bilder):
    lm_server.delay = 1.0
    with pytest.raises(Exception) as exc:
        client.transcribe("m", bilder, "p", timeout=0.2)
    assert "timed out" in str(exc.value)


def test_transcribe_server_nicht_erreichbar(fake_lms, bilder):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    offline = llm.LMStudio(f"http://127.0.0.1:{port}/v1")
    with pytest.raises(urllib.error.URLError):  # wird nicht umgewandelt, main() fängt es pro Dokument ab
        offline.transcribe("m", bilder, "p", timeout=2)


# ---------------------------------------------------------------- transcribe_file

def test_transcribe_file_gesamtkette(client, lm_server, bilder, tmp_path, monkeypatch):
    seen = {}

    def fake_prepare(original, max_size, max_pages, workdir):
        seen.update(original=original, max_size=max_size, max_pages=max_pages, workdir=workdir)
        assert workdir.is_dir()
        return bilder

    monkeypatch.setattr(llm, "prepare_images", fake_prepare)
    lm_server.reply(content='```html\n<p>Text</p>\n```', usage={"completion_tokens": 3})

    html, usage, seconds, n = client.transcribe_file("m", tmp_path / "foto.jpg", "Prompt", 1234, 2, 10)

    assert html == "<p>Text</p>"                    # Code-Fence entfernt
    assert usage == {"completion_tokens": 3} and n == 2 and seconds >= 0
    assert (seen["max_size"], seen["max_pages"]) == (1234, 2)
    assert lm_server.requests[0][1]["messages"][0]["content"][0]["text"] == "Prompt"
    assert not seen["workdir"].exists()             # Temp-Ordner aufgeräumt


def test_transcribe_file_raeumt_temp_ordner_auch_bei_fehler_auf(client, lm_server, bilder, tmp_path, monkeypatch):
    workdirs = []
    monkeypatch.setattr(llm, "prepare_images", lambda o, s, p, w: workdirs.append(w) or bilder)
    lm_server.status = 500
    with pytest.raises(RuntimeError):
        client.transcribe_file("m", tmp_path / "foto.jpg", timeout=10)
    assert not workdirs[0].exists()


def test_transcribe_file_standardwerte(client, lm_server, bilder, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "prepare_images", lambda o, s, p, w: seen.update(s=s, p=p) or bilder)
    client.transcribe_file("m", tmp_path / "x.jpg", timeout=10)
    assert (seen["s"], seen["p"]) == (2000, 5)
    assert lm_server.requests[0][1]["messages"][0]["content"][0]["text"] == llm.PROMPT
