"""Tests für den Ablauf von paperplus.main() gegen Fake-Paperless und ein Fake-LM-Studio.

Schwerpunkt: der Schreibpfad. Paperless-Inhalte werden überschrieben, deshalb muss genau
feststehen, wann (nicht) geschrieben wird und welche Tags dabei entstehen.
"""
import sys

import pytest

import llm
import paperplus
from fake_lmstudio import HTML, FakeLM
from fake_paperless import TOKEN

TEXT = "Hallo Welt\nZweite Zeile"


@pytest.fixture
def env(paperless, tmp_path, monkeypatch):
    """Alles, was main() von außen braucht – ohne echte .env, LM Studio oder macOS."""
    FakeLM.instances, FakeLM.responder = [], None
    monkeypatch.setattr(llm, "LMStudio", FakeLM)
    monkeypatch.setenv("PAPERLESS_URL", paperless.url)
    monkeypatch.setenv("PAPERLESS_TOKEN", TOKEN)
    monkeypatch.setattr(paperplus, "on_ac_power", lambda: True)
    notes = []
    monkeypatch.setattr(paperplus, "notify", notes.append)
    paperless.marker = paperless.add_tag(paperplus.MARKER)
    paperless.queue = paperless.add_tag(paperplus.QUEUE_TAG)
    paperless.out = tmp_path / "ausgabe"
    paperless.notes = notes
    return paperless


def run(env, monkeypatch, *args, model="testmodell"):
    argv = ["paperplus.py", "--out", str(env.out), *args]
    if model:
        argv += ["--model", model]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        paperplus.main()
    return exc.value.code


def lm():
    (instance,) = FakeLM.instances
    return instance


# ---------------------------------------------------------------- Normalfall

def test_foto_wird_angereichert(env, monkeypatch, capsys):
    env.add_document(10, title="Beleg", tags=[3])
    assert run(env, monkeypatch) == 0

    (patch,) = env.patches()
    assert patch[1] == "/api/documents/10/"
    assert patch[3] == {"content": f"{TEXT}\n\nllm-angereichert (testmodell)", "tags": sorted([3, env.marker])}
    assert "1 angereichert, 0 Fehler" in capsys.readouterr().out


def test_html_wird_lokal_gespeichert(env, monkeypatch):
    env.add_document(10, title="Beleg", original=b"BILD")
    run(env, monkeypatch)
    folder = env.out / "10_Beleg"
    assert (folder / "original.jpg").read_bytes() == b"BILD"
    assert (folder / "testmodell.html").read_text(encoding="utf-8") == HTML + "\n"


def test_queue_tag_wird_entfernt_fremde_tags_bleiben(env, monkeypatch):
    env.add_document(10, tags=[env.queue, 77])
    run(env, monkeypatch)
    assert env.docs[10]["tags"] == sorted([77, env.marker])


def test_pdf_mit_queue_tag_wird_angereichert(env, monkeypatch):
    env.add_document(11, file_name="scan.pdf", mime="application/pdf", tags=[env.queue], archived=True)
    assert run(env, monkeypatch) == 0
    assert env.docs[11]["content"].endswith("llm-angereichert (testmodell)")
    assert lm().transcribed[0].name == "original.pdf"


def test_bereits_angereichertes_dokument_in_warteschlange_wird_erneut_verarbeitet(env, monkeypatch):
    env.add_document(10, tags=[env.marker, env.queue])
    assert run(env, monkeypatch) == 0
    assert env.docs[10]["tags"] == [env.marker]  # Queue-Tag weg, Marker bleibt


def test_zwischenzeitlich_geaenderte_tags_gehen_nicht_verloren(env, monkeypatch):
    env.add_document(10, tags=[])
    # Nach dem ersten Abruf (store_document) setzt jemand in Paperless einen weiteren Tag
    env.on_document_get[10] = lambda doc, n: doc["tags"].append(99) if n == 1 else None
    run(env, monkeypatch)
    assert 99 in env.docs[10]["tags"] and env.marker in env.docs[10]["tags"]


def test_mehrere_dokumente_neueste_zuerst_lm_wird_einmal_gestartet(env, monkeypatch):
    for i in (3, 9, 5):
        env.add_document(i, title=f"d{i}")
    run(env, monkeypatch)
    assert [p[1] for p in env.patches()] == ["/api/documents/9/", "/api/documents/5/", "/api/documents/3/"]
    assert len(FakeLM.instances) == 1
    assert lm().events == ["start_server", ("load_model", "testmodell", 16384), "unload"]


def test_marker_tag_wird_angelegt_wenn_er_fehlt(env, monkeypatch):
    env.tags[:] = [t for t in env.tags if t["name"] != paperplus.MARKER]
    env.add_document(10)
    assert run(env, monkeypatch) == 0
    (post,) = env.calls("POST", "/api/tags")
    assert post[3]["name"] == paperplus.MARKER
    new_tag = [t["id"] for t in env.tags if t["name"] == paperplus.MARKER][0]
    assert new_tag in env.docs[10]["tags"]


def test_modell_wird_nach_dem_lauf_entladen_ausser_mit_keep_loaded(env, monkeypatch):
    env.add_document(10)
    run(env, monkeypatch, "--keep-loaded")
    assert "unload" not in lm().events


def test_ids_werden_direkt_verarbeitet_ohne_auswahl(env, monkeypatch):
    env.add_document(10)
    env.add_document(11)
    run(env, monkeypatch, "10")
    assert [p[1] for p in env.patches()] == ["/api/documents/10/"]


def test_latest_begrenzt_auf_die_neuesten_ausstehenden(env, monkeypatch, capsys):
    for i in (1, 2, 3):
        env.add_document(i)
    run(env, monkeypatch, "--latest", "2")
    assert sorted(p[1] for p in env.patches()) == ["/api/documents/2/", "/api/documents/3/"]
    assert "davon die 2 neuesten: #3, #2" in capsys.readouterr().out


# ---------------------------------------------------------------- Dokumente überspringen

def test_nichts_zu_tun(env, monkeypatch, capsys):
    env.add_document(10, tags=[env.marker])
    assert run(env, monkeypatch) == 0
    assert "Nichts zu tun" in capsys.readouterr().out
    assert FakeLM.instances == [] and env.patches() == []


def test_angereichertes_dokument_per_id_wird_ohne_force_uebersprungen(env, monkeypatch, capsys):
    env.add_document(10, tags=[env.marker])
    assert run(env, monkeypatch, "10") == 0
    assert "übersprungen" in capsys.readouterr().out
    assert FakeLM.instances == [] and env.patches() == []  # LM Studio wird gar nicht erst gestartet


def test_force_verarbeitet_auch_angereicherte_dokumente(env, monkeypatch):
    env.add_document(10, tags=[env.marker])
    assert run(env, monkeypatch, "10", "--force") == 0
    assert len(env.patches()) == 1


# ---------------------------------------------------------------- Nichts schreiben

def test_no_write_laesst_paperless_unveraendert(env, monkeypatch):
    env.add_document(10, content="alt", tags=[3])
    assert run(env, monkeypatch, "--no-write") == 0
    assert env.patches() == [] and env.calls("POST") == []
    assert env.docs[10]["content"] == "alt" and env.docs[10]["tags"] == [3]
    assert (env.out / "10_Testdokument" / "testmodell.html").exists()  # lokal wird trotzdem gespeichert


def test_no_write_legt_keinen_tag_an(env, monkeypatch):
    env.tags[:] = [t for t in env.tags if t["name"] != paperplus.MARKER]
    env.add_document(10)
    run(env, monkeypatch, "--no-write")
    assert env.calls("POST") == []


def test_skip_llm_laedt_nur_herunter(env, monkeypatch, capsys):
    env.add_document(10, original=b"BILD")
    assert run(env, monkeypatch, "--skip-llm", model=None) == 0  # ohne Modell erlaubt
    assert FakeLM.instances == [] and env.patches() == [] and env.calls("POST") == []
    assert (env.out / "10_Testdokument" / "original.jpg").read_bytes() == b"BILD"
    assert "übersprungen" in capsys.readouterr().out


def test_skip_llm_ein_fehlerhaftes_dokument_stoppt_die_anderen_nicht(env, monkeypatch, capsys):
    env.add_document(10, file_name="daten.csv", mime="text/csv")  # nicht unterstützt
    env.add_document(11)
    run(env, monkeypatch, "10", "11", "--skip-llm", model=None)
    assert (env.out / "11_Testdokument" / "original.jpg").exists()
    assert "#10" in capsys.readouterr().err


# ---------------------------------------------------------------- Fehlerfälle

def test_leerer_llm_text_schreibt_nichts(env, monkeypatch, capsys):
    env.add_document(10, content="Tesseract bleibt")
    FakeLM.responder = lambda original: '<div data-label="Image"><img alt="Logo"/></div>'
    assert run(env, monkeypatch) == 1
    assert env.patches() == [] and env.docs[10]["content"] == "Tesseract bleibt"
    captured = capsys.readouterr()
    assert "keinen Text geliefert" in captured.err
    assert "0 angereichert, 1 Fehler" in captured.out


def test_ein_fehler_stoppt_die_anderen_dokumente_nicht(env, monkeypatch, capsys):
    env.add_document(10, title="gut")
    env.add_document(11, title="kaputt")

    def responder(original):
        if "kaputt" in str(original):
            raise RuntimeError("Modell abgestürzt")
        return HTML
    FakeLM.responder = responder

    assert run(env, monkeypatch) == 1
    assert [p[1] for p in env.patches()] == ["/api/documents/10/"]
    captured = capsys.readouterr()
    assert "#11: Modell abgestürzt" in captured.err
    assert "1 angereichert, 1 Fehler" in captured.out
    assert "unload" in lm().events  # Modell wird trotz Fehler entladen


def test_schreibfehler_in_paperless_zaehlt_als_fehler(env, monkeypatch, capsys):
    env.add_document(10)
    env.fail[("PATCH", "/api/documents/10")] = 500
    assert run(env, monkeypatch) == 1
    assert "#10" in capsys.readouterr().err


def test_unbekannte_id_ist_fehler_ohne_abbruch(env, monkeypatch, capsys):
    env.add_document(10)
    assert run(env, monkeypatch, "999", "10") == 1
    assert [p[1] for p in env.patches()] == ["/api/documents/10/"]
    assert "#999" in capsys.readouterr().err


def test_kein_modell_ist_fehler(env, monkeypatch, capsys):
    assert run(env, monkeypatch, model=None) == 1
    assert "Kein Modell" in capsys.readouterr().err
    assert env.requests == []


def test_kein_token_ist_fehler(env, monkeypatch, capsys):
    monkeypatch.delenv("PAPERLESS_TOKEN")
    assert run(env, monkeypatch) == 1
    assert "PAPERLESS_TOKEN fehlt" in capsys.readouterr().err
    assert env.requests == []


def test_falsches_token_bricht_vor_jeder_aenderung_ab(env, monkeypatch, capsys):
    monkeypatch.setenv("PAPERLESS_TOKEN", "falsch")
    env.add_document(10)
    assert run(env, monkeypatch) == 1
    assert "Token ungültig" in capsys.readouterr().err
    assert env.patches() == [] and FakeLM.instances == []


# ---------------------------------------------------------------- --auto (Zeitplan)

def test_auto_auf_akku_beendet_sich_ohne_anfragen(env, monkeypatch, capsys):
    monkeypatch.setattr(paperplus, "on_ac_power", lambda: False)
    env.add_document(10)
    assert run(env, monkeypatch, "--auto") == 0
    assert "Akku" in capsys.readouterr().out
    assert env.requests == [] and env.notes == []


def test_auto_ohne_paperless_beendet_sich_still(env, monkeypatch, capsys):
    env.stop()
    try:
        assert run(env, monkeypatch, "--auto") == 0
    finally:
        env.start()  # damit das Fixture-Teardown sauber stoppen kann
    assert "nicht erreichbar" in capsys.readouterr().out
    assert env.notes == []


def test_auto_meldet_ergebnis_per_mitteilung(env, monkeypatch):
    env.add_document(10)
    assert run(env, monkeypatch, "--auto") == 0
    assert env.notes == ["1 Dokument(e) angereichert"]


def test_auto_meldet_fehler_in_der_mitteilung(env, monkeypatch):
    env.add_document(10)
    FakeLM.responder = lambda original: ""
    assert run(env, monkeypatch, "--auto") == 1
    assert env.notes == ["0 Dokument(e) angereichert, 1 Fehler"]


def test_auto_ohne_arbeit_keine_mitteilung(env, monkeypatch):
    assert run(env, monkeypatch, "--auto") == 0
    assert env.notes == []


def test_ohne_auto_keine_mitteilung(env, monkeypatch):
    env.add_document(10)
    run(env, monkeypatch)
    assert env.notes == []
